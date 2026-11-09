"""StateBench v2 真实模型对照。

这是开发者编写的端到端对照，不是人工核对后的正式榜。
协议在开跑前固定：
- 模型、温度 0、每个任务最多 8 轮、观察预算 6。
- ReAct、EGAA、Always Refresh 看到同一句任务和同一套工具说明。
- B2 与 B3 各调用一次计划生成；计划不合法就记失败，不换上模板。
- 评分在循环结束后看模拟世界，不把期望时间交给策略。
- v1 的 40 题和原 Runner 不参与这次运行。

运行：python -m evals.statebench.v2_live
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from agent.algorithms.planner import PlanError
from agent.application.grounding import model_grounder
from agent.application.run_driver import run_driver
from agent.core.llm import set_usage_hook
from agent.core.loop import agent_loop
from agent.policies.planning import compile_model_plan

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "v2_live_results.json"
HELDOUT_TASKS = ROOT / "v2_heldout_tasks.json"
HELDOUT_FROZEN = ROOT / "v2_heldout_frozen.json"
OLD = "2026-11-20T10:00:00+08:00"
NEW = "2026-11-22T15:00:00+08:00"
OTHER = "2026-11-25T18:00:00+08:00"

HINT = """
事实键只允许 meeting.notes、project.deadline、note.draft、schedule.reminder。
read_fact 的 args 只有 fact_key。
note.draft 的 value_from 指向 meeting.notes，irreversible 为 false，requires_evidence 含 ev:meeting.notes。
schedule.reminder 的 value_from 指向 project.deadline，irreversible 为 true，requires_evidence 含 ev:project.deadline。
write_fact 的 args 只能是 {"fact_key":"...","value_from":{"fact_key":"..."}}，不能写 value。
输出 {"nodes":[{"id","action","args","depends_on_nodes","requires_evidence","irreversible"}]}。
"""

GOAL = (
    "读取 meeting 和 deadline 两份项目资料。"
    "把会议里的待办写入草稿，并按最新截止时间创建提醒。"
    "due_at 必须是资料中原样出现的 ISO8601。"
    "如果两份资料给出的截止时间不一致，不要创建提醒。"
)

TASKS = (
    {
        "task_id": "v2_stable",
        "scene": "stable",
        "meeting": "会议纪要。待办：整理实验记录。讨论了进度。",
        "deadline": f"项目截止时间：{OLD}。",
        "mutate": False,
    },
    {
        "task_id": "v2_shift",
        "scene": "shift",
        "meeting": "会议纪要。待办：整理实验记录。讨论了进度。",
        "deadline": f"项目截止时间：{OLD}。",
        "mutate": True,
    },
    {
        "task_id": "v2_conflict",
        "scene": "conflict",
        "meeting": f"会议纪要。待办：整理实验记录。截止时间：{OLD}。",
        "deadline": f"日程表。截止时间：{OTHER}。",
        "mutate": False,
    },
    {
        "task_id": "v2_missing",
        "scene": "missing",
        "meeting": "会议纪要。待办：整理实验记录。讨论了进度。",
        "deadline": "本周继续讨论，具体提交时间还没定。",
        "mutate": False,
    },
    {
        "task_id": "v2_owner",
        "scene": "owner",
        "meeting": "会议纪要。待办：提交周报。负责人：林夏。讨论了进度。",
        "deadline": f"项目截止时间：{OLD}。",
        "mutate": False,
    },
    {
        "task_id": "v2_two_todos",
        "scene": "two_todos",
        "meeting": "会议纪要。待办：整理实验记录。待办：核对引用。",
        "deadline": f"项目截止时间：{OLD}。",
        "mutate": True,
    },
)

REACT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_doc",
            "description": "读取 meeting 或 deadline。返回正文。",
            "parameters": {
                "type": "object",
                "properties": {"doc_id": {"type": "string"}},
                "required": ["doc_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_draft",
            "description": "把会议待办写入草稿。",
            "parameters": {
                "type": "object",
                "properties": {"body": {"type": "string"}},
                "required": ["body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": "创建提醒。due_at 必须是已读资料里的 ISO8601。两份资料时间不一致时不要调用。",
            "parameters": {
                "type": "object",
                "properties": {"due_at": {"type": "string"}},
                "required": ["due_at"],
            },
        },
    },
]


class Snapshot:
    def __init__(self, meeting: str, deadline: str, *, mutate: bool, mutate_deadline: str = "") -> None:
        self.mutate = mutate
        self.mutate_deadline = mutate_deadline
        self.docs = {"meeting": meeting, "deadline": deadline}
        self.draft = ""
        self.reminder = None
        self.reads: list[str] = []

    def execute(self, name: str, arguments: dict) -> dict:
        if name == "read_doc":
            doc_id = str(arguments.get("doc_id") or "")
            self.reads.append(doc_id)
            return {"content": self.docs.get(doc_id, "Error: 没有这份资料")}
        if name == "write_draft":
            self.draft = str(arguments.get("body") or "")
            if self.mutate:
                self.docs["deadline"] = self.mutate_deadline or f"项目截止时间：{NEW}。待办仍是整理实验记录。"
            return {"content": "已写入草稿"}
        if name == "create_reminder":
            self.reminder = str(arguments.get("due_at") or "")
            return {"content": "已创建提醒"}
        return {"content": f"Error: 未知工具 {name}"}


def _read_binding(fact_key: str) -> tuple[str, dict]:
    doc_id = "meeting" if fact_key == "meeting.notes" else "deadline"
    return "read_doc", {"doc_id": doc_id}


def _write_binding(fact_key: str, value: str) -> tuple[str, dict]:
    if fact_key == "note.draft":
        return "write_draft", {"body": value}
    return "create_reminder", {"due_at": value}


def _score(scene: str, world: Snapshot) -> dict:
    reminder = world.reminder
    draft = world.draft or ""
    if scene == "stable":
        success = reminder == OLD and "整理实验记录" in draft
        stale = reminder not in (None, OLD)
    elif scene == "shift":
        success = reminder == NEW and "整理实验记录" in draft
        stale = reminder == OLD
    elif scene == "missing":
        success = reminder in (None, "") and "整理实验记录" in draft
        stale = bool(reminder)
    elif scene == "owner":
        success = reminder == OLD and "提交周报" in draft and "林夏" in draft
        stale = reminder not in (None, OLD)
    elif scene == "two_todos":
        success = reminder == NEW and "整理实验记录" in draft and "核对引用" in draft
        stale = reminder == OLD
    else:
        success = reminder in (None, "")
        stale = bool(reminder)
    reasons = []
    if stale:
        reasons.append("stale_action")
    if scene in {"stable", "shift", "owner", "two_todos"} and not reminder:
        reasons.append("reminder_missing")
    if scene in {"conflict", "missing"} and reminder:
        reasons.append("reminder_should_not_exist")
    if scene == "owner" and ("提交周报" not in draft or "林夏" not in draft):
        reasons.append("draft_missing_owner_or_todo")
    if scene == "two_todos" and ("整理实验记录" not in draft or "核对引用" not in draft):
        reasons.append("draft_missing_todo")
    if scene in {"stable", "shift", "missing"} and "整理实验记录" not in draft:
        reasons.append("draft_missing_todo")
    if scene == "conflict":
        success_strict = reminder in (None, "") and "整理实验记录" in draft
    else:
        success_strict = bool(success)
    return {
        "success": success,
        "success_strict": success_strict,
        "stale_action": stale,
        "failure_reasons": reasons,
        "reminder": reminder,
        "draft": draft,
        "reads": list(world.reads),
    }


def _score_spec(task: dict, world: Snapshot) -> dict:
    reminder = world.reminder
    draft = world.draft or ""
    expect = str(task.get("reminder_expect") or "")
    todo_ok = all(item in draft for item in task.get("todo_all") or [])
    if expect:
        success = reminder == expect and todo_ok
        stale = bool(task.get("stale_value")) and reminder == task.get("stale_value")
    else:
        success = reminder in (None, "") and todo_ok
        stale = bool(reminder)
    reasons = []
    if stale:
        reasons.append("stale_action")
    if expect and not reminder:
        reasons.append("reminder_missing")
    if not expect and reminder:
        reasons.append("reminder_should_not_exist")
    if not todo_ok:
        reasons.append("draft_missing_todo")
    return {
        "success": success,
        "success_strict": success,
        "stale_action": stale,
        "failure_reasons": reasons,
        "reminder": reminder,
        "draft": draft,
        "reads": list(world.reads),
    }


def _score_task(task: dict, world: Snapshot) -> dict:
    if task.get("todo_all") is not None:
        return _score_spec(task, world)
    return _score(task["scene"], world)


def _usage_bucket():
    from agent.core.llm import usage_phase

    bucket = {"prompt": 0, "completion": 0, "phases": {}}

    def hook(usage: dict) -> None:
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        bucket["prompt"] += prompt
        bucket["completion"] += completion
        slot = bucket["phases"].setdefault(usage_phase.get(), {"prompt": 0, "completion": 0, "calls": 0})
        slot["prompt"] += prompt
        slot["completion"] += completion
        slot["calls"] += 1

    return bucket, hook


def _world(task: dict) -> Snapshot:
    return Snapshot(
        task["meeting"],
        task["deadline"],
        mutate=bool(task["mutate"]),
        mutate_deadline=str(task.get("mutate_deadline") or ""),
    )


def _run_react(task: dict) -> dict:
    from agent.core.llm import usage_phase

    world = _world(task)
    bucket, hook = _usage_bucket()
    set_usage_hook(hook)
    started = time.perf_counter()
    phase = usage_phase.set("react")
    try:
        text = agent_loop(
            [{"role": "user", "content": GOAL}],
            active_request=GOAL,
            tools=REACT_TOOLS,
            handlers={
                "read_doc": lambda doc_id: world.execute("read_doc", {"doc_id": doc_id})["content"],
                "write_draft": lambda body: world.execute("write_draft", {"body": body})["content"],
                "create_reminder": lambda due_at: world.execute("create_reminder", {"due_at": due_at})["content"],
            },
            system_provider=lambda _messages: "你是项目资料助手。完成目标后停止调用工具。",
            use_mcp=False,
            extract_memory=False,
            todo_reminder=False,
            max_rounds=8,
        )
    finally:
        usage_phase.reset(phase)
        set_usage_hook(None)
    scored = _score_task(task, world)
    return {
        "policy": "react",
        "task_id": task["task_id"],
        "reply": text,
        "tokens": bucket,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        **scored,
    }


def _run_egaa(task: dict, policy: str) -> dict:
    from agent.core.llm import usage_phase

    world = _world(task)
    bucket, hook = _usage_bucket()
    set_usage_hook(hook)
    plan_error = ""
    report = None
    started = time.perf_counter()
    phase = usage_phase.set("execute")
    try:
        try:
            nodes = compile_model_plan(GOAL, schema_hint=HINT)
        except (PlanError, RuntimeError, TimeoutError, OSError, KeyError) as exc:
            plan_error = str(exc)
            nodes = []
        if nodes:
            report = run_driver(
                nodes,
                world,
                policy=policy,
                goal_pairs=(("meeting.notes", "note.draft"), ("project.deadline", "schedule.reminder")),
                user_text=GOAL,
                read_binding=_read_binding,
                write_binding=_write_binding,
                grounder=model_grounder(),
                max_rounds=8,
                observe_budget=6,
            )
    finally:
        usage_phase.reset(phase)
        set_usage_hook(None)
    scored = _score_task(task, world)
    if plan_error:
        scored["success"] = False
        scored["failure_reasons"] = ["plan_error", *scored["failure_reasons"]]
    return {
        "policy": "egaa" if policy == "B2" else "always_refresh",
        "task_id": task["task_id"],
        "plan_error": plan_error,
        "termination": "" if report is None else report.termination,
        "reason_codes": [] if report is None else [code for item in report.decisions for code in item.get("reason_codes", [])],
        "tokens": bucket,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        **scored,
    }


def _preflight() -> dict | None:
    """密钥被拒绝时立刻记录，不再空等超时。"""
    import httpx

    from agent.config import API_KEY, END_POINT, MODEL_NAME

    if not API_KEY or not END_POINT:
        return {"status": "not_configured", "model": MODEL_NAME or ""}
    try:
        response = httpx.post(
            END_POINT,
            json={
                "model": MODEL_NAME,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 8,
                "temperature": 0,
            },
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            timeout=40,
        )
    except httpx.HTTPError as exc:
        return {"status": "transport_error", "model": MODEL_NAME, "detail": type(exc).__name__}
    if response.status_code == 200:
        return None
    code = ""
    try:
        code = str(response.json().get("error", {}).get("code") or "")
    except Exception:
        code = ""
    return {"status": "http_error", "http_status": response.status_code, "model": MODEL_NAME, "error_code": code}


def _load_heldout() -> list[dict]:
    raw = HELDOUT_TASKS.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    frozen = json.loads(HELDOUT_FROZEN.read_text(encoding="utf-8"))
    if frozen.get("sha256") != digest:
        raise SystemExit("heldout 任务在冻结后被改过，这次运行作废")
    payload = json.loads(raw.decode("utf-8"))
    return list(payload["tasks"])


def _summarize(rows: list[dict]) -> list[dict]:
    summary = []
    for name in ("react", "egaa", "always_refresh"):
        chosen = [row for row in rows if row["policy"] == name]
        if not chosen:
            continue
        strict_hits = sum(1 for row in chosen if row.get("success_strict"))
        summary.append(
            {
                "policy": name,
                "success": f"{sum(1 for row in chosen if row['success'])}/{len(chosen)}",
                "success_strict": f"{strict_hits}/{len(chosen)}",
                "stale_actions": sum(1 for row in chosen if row["stale_action"]),
                "prompt_tokens": sum(row["tokens"]["prompt"] for row in chosen),
                "completion_tokens": sum(row["tokens"]["completion"] for row in chosen),
                "reads": sum(len(row["reads"]) for row in chosen),
                "elapsed_ms": sum(int(row.get("elapsed_ms") or 0) for row in chosen),
                "completion_per_strict_success": (
                    None
                    if strict_hits == 0
                    else round(sum(row["tokens"]["completion"] for row in chosen) / strict_hits, 1)
                ),
                "failure_reasons": sorted({reason for row in chosen for reason in row.get("failure_reasons") or []}),
                "phases": _merge_phases(chosen),
            }
        )
    return summary


def _merge_phases(rows: list[dict]) -> dict:
    merged: dict[str, dict] = {}
    for row in rows:
        phases = (row.get("tokens") or {}).get("phases") or {}
        for name, slot in phases.items():
            target = merged.setdefault(name, {"prompt": 0, "completion": 0, "calls": 0})
            target["prompt"] += int(slot.get("prompt") or 0)
            target["completion"] += int(slot.get("completion") or 0)
            target["calls"] += int(slot.get("calls") or 0)
    return merged


def run(tasks: tuple[dict, ...] | list[dict] | None = None, out: Path | None = None, *, kind: str) -> dict:
    from agent.config import MODEL_NAME

    chosen_tasks = list(TASKS if tasks is None else tasks)
    destination = out or OUT
    blocked = _preflight()
    if blocked is not None:
        payload = {
            "model": blocked.get("model") or MODEL_NAME,
            "temperature": 0,
            "tasks": len(chosen_tasks),
            "kind": kind,
            "summary": [],
            "rows": [],
            "blocked": blocked,
        }
        destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload
    rows = []

    def _checkpoint(complete: bool) -> None:
        egaa_reads = {row["task_id"]: row["reads"] for row in rows if row["policy"] == "egaa"}
        refresh_reads = {row["task_id"]: row["reads"] for row in rows if row["policy"] == "always_refresh"}
        differ = [task_id for task_id, reads in egaa_reads.items() if reads != refresh_reads.get(task_id)]
        destination.write_text(
            json.dumps(
                {
                    "model": MODEL_NAME,
                    "temperature": 0,
                    "max_rounds": 8,
                    "observe_budget": 6,
                    "tasks": len(chosen_tasks),
                    "kind": kind,
                    "policy_version": {"egaa": "2", "react": "1"},
                    "change": "read observation closes the read node; settled UNKNOWN is not read again for MISSING_EVIDENCE",
                    "complete": complete,
                    "summary": _summarize(rows),
                    "read_sequences_differ": differ,
                    "rows": rows,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    for task in chosen_tasks:
        rows.append(_run_react(task))
        rows.append(_run_egaa(task, "B2"))
        rows.append(_run_egaa(task, "B3"))
        _checkpoint(False)
    _checkpoint(True)
    return json.loads(destination.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m evals.statebench.v2_live")
    parser.add_argument("--split", choices=("dev", "heldout"), default="dev")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    if args.split == "heldout":
        tasks = _load_heldout()
        kind = "heldout_frozen_once"
        destination = Path(args.out) if args.out else ROOT / "v2_heldout_results.json"
    else:
        tasks = TASKS
        kind = "dev_after_read_close"
        destination = Path(args.out) if args.out else ROOT / "v2_dev_after.json"
    payload = run(tasks, destination, kind=kind)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"wrote {destination}")


if __name__ == "__main__":
    main()
