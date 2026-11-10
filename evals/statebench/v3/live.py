"""StateBench v3 真实模型运行。评分在回合结束后看隐藏世界。

预算按依赖图上限事先取定：最多 3 次读取、每次可能再读一遍、再加上写入。
不因为某次开发结果再改这个预算。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path

from agent.algorithms.planner import PlanError
from agent.algorithms.types import ChangeNotice, Evidence
from agent.application.run_driver import run_driver
from agent.core.llm import set_usage_hook, usage_phase
from agent.core.loop import agent_loop
from agent.policies.planning import compile_model_plan
from evals.statebench.v3.catalog import all_tasks
from evals.statebench.v3.statistics import clustered_bootstrap
from evals.statebench.v3.world import World, score

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00")
MAX_ROUNDS = 16
OBSERVE_BUDGET = 12
REPLAN_BUDGET = 2
POLICY_CODE = {
    "react": "",
    "egaa": "B2",
    "always_refresh": "B3",
    "plan_only": "B1",
    "always_full_replan": "B4",
}
PRIMARY = ("react", "egaa", "always_refresh")
DIAGNOSTIC = ("plan_only", "always_full_replan")


def public_view(task: dict) -> dict:
    titles = list(task["titles"].values())
    draft_count = sum(1 for item in task["writes"] if item["kind"] == "draft")
    return {
        "task_id": task["task_id"],
        "public_goal": task["public_goal"],
        "titles": titles,
        "draft_count": draft_count,
        "allowed_tools": list(task["allowed_tools"]),
    }


def schema_hint(task: dict) -> str:
    titles = "、".join(public_view(task)["titles"])
    drafts = public_view(task)["draft_count"]
    draft_keys = [f"draft:{index}" for index in range(1, drafts + 1)]
    keys = "、".join(draft_keys + ["schedule.reminder"])
    return (
        f"可读事实键就是这些文档标题：{titles}。"
        "read_fact 的 args 只有 fact_key，fact_key 必须是其中一个标题。"
        f"可写事实键：{keys}。"
        'write_fact 的 args 必须有 fact_key 和 value_from。value_from 写成 {"fact_key": "已经读取的文档标题"}。'
        "depends_on_nodes 填写依赖的节点 id，不要写成 true。"
        "只有目标明确要求只保留待办句时，才把草稿键写成 draft:N#todo；只保留负责人时用 draft:N#owner。"
        "不要对同一个槽同时输出全文键和后缀键。"
        "schedule.reminder 的 irreversible 为 true，时间从 value_from 的原文提取。"
        "原文没有 ISO8601，或目标要求冲突、缺失时不要提醒，就不要输出 schedule.reminder。"
        '只输出 {"nodes":[{"id","action","args","depends_on_nodes","requires_evidence","irreversible"}]}。'
    )


def _project(value: str, fact_key: str) -> str:
    if fact_key == "schedule.reminder":
        found = ISO.findall(value or "")
        return found[-1] if found else ""
    if fact_key.endswith("#todo"):
        parts = [part for part in (value or "").replace("｜", "。").split("。") if "待办" in part]
        return "。".join(parts)
    if fact_key.endswith("#owner"):
        parts = [part for part in (value or "").split("。") if "负责人" in part]
        return "。".join(parts)
    return value or ""


class Adapter:
    def __init__(self, task: dict) -> None:
        self.task = task
        self.world = World(task)
        self.by_title = {item["title"]: item["sid"] for item in task["sources"]}
        self.draft_slots = [item["slot"] for item in task["writes"] if item["kind"] == "draft"]
        self.seen_notices: set[str] = set()

    def execute(self, name: str, arguments: dict) -> dict:
        if name == "read_doc":
            sid = self.by_title.get(str(arguments.get("doc_id") or ""), "")
            return self.world.read(sid or str(arguments.get("doc_id") or ""))
        if name == "write_draft":
            slot = self._slot(str(arguments.get("slot") or ""))
            body = _project(str(arguments.get("body") or ""), str(arguments.get("pick") or "all"))
            return {"content": self.world.write_draft(slot, body)}
        if name == "create_reminder":
            due = _project(str(arguments.get("due_at") or ""), "schedule.reminder") or str(arguments.get("due_at") or "")
            return {"content": self.world.create_reminder(due)}
        if name == "list_notices":
            payload = self.world.list_notices()
            return {"content": "\n".join(payload["notices"]) or "没有新通知"}
        return {"content": f"Error: 未知工具 {name}"}

    def _slot(self, raw: str) -> str:
        if raw in self.draft_slots:
            return raw
        if raw.isdigit():
            index = int(raw) - 1
            if 0 <= index < len(self.draft_slots):
                return self.draft_slots[index]
        return self.draft_slots[0] if self.draft_slots else "todo"

    def notices(self, now: int, _nodes: list) -> list[ChangeNotice]:
        found = []
        for text in self.world.notices:
            title = text.split(" 已更新", 1)[0]
            notice_id = f"n:{title}"
            if notice_id in self.seen_notices:
                continue
            self.seen_notices.add(notice_id)
            found.append(ChangeNotice(notice_id, title, now))
        return found


def _ground(*, fact_key: str, content: str, observed_at: int, ledger) -> Evidence:
    text = "" if content.startswith("Error:") else content.strip()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    version, status = ledger.assign(fact_key, f"doc:{fact_key}", digest, text)
    if not text:
        status = "UNKNOWN"
    return Evidence(
        id=f"ev:{fact_key}",
        fact_key=fact_key,
        value=text,
        source_id=f"doc:{fact_key}",
        source_version=version or "unversioned",
        observed_at=observed_at,
        status=status if version else "UNKNOWN",
    )


def _add(current, value):
    if value is None:
        return current
    return int(value if current is None else current + int(value))


def _usage():
    bucket = {"prompt": None, "completion": None, "phases": {}, "missing_calls": 0}

    def hook(usage: dict) -> None:
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        phase = usage_phase.get()
        slot = bucket["phases"].setdefault(phase, {"prompt": None, "completion": None, "calls": 0, "missing": 0})
        slot["calls"] += 1
        if prompt is None and completion is None:
            bucket["missing_calls"] += 1
            slot["missing"] += 1
            return
        if prompt is None or completion is None:
            bucket["missing_calls"] += 1
            slot["missing"] += 1
        bucket["prompt"] = _add(bucket["prompt"], prompt)
        bucket["completion"] = _add(bucket["completion"], completion)
        slot["prompt"] = _add(slot["prompt"], prompt)
        slot["completion"] = _add(slot["completion"], completion)

    return bucket, hook


def _tools(task: dict) -> list[dict]:
    titles = public_view(task)["titles"]
    return [
        {
            "type": "function",
            "function": {
                "name": "read_doc",
                "description": "读取一份资料。doc_id 只能是：" + "、".join(titles),
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
                "description": "写入草稿。slot 从 1 开始。pick 可以是 all、todo、owner。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "slot": {"type": "string"},
                        "body": {"type": "string"},
                        "pick": {"type": "string"},
                    },
                    "required": ["slot", "body"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_reminder",
                "description": "创建提醒。due_at 必须是已读原文中的 ISO8601。没有依据或时间冲突时不要调用。",
                "parameters": {
                    "type": "object",
                    "properties": {"due_at": {"type": "string"}},
                    "required": ["due_at"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_notices",
                "description": "查看资料更新通知。通知不含新正文，需要再读原文。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]


def _handlers(adapter: Adapter) -> dict:
    def read_doc(doc_id: str) -> str:
        return str(adapter.execute("read_doc", {"doc_id": doc_id})["content"])

    def write_draft(slot: str, body: str, pick: str = "all") -> str:
        return str(adapter.execute("write_draft", {"slot": slot, "body": body, "pick": pick})["content"])

    def create_reminder(due_at: str) -> str:
        return str(adapter.execute("create_reminder", {"due_at": due_at})["content"])

    def list_notices() -> str:
        return str(adapter.execute("list_notices", {})["content"])

    return {
        "read_doc": read_doc,
        "write_draft": write_draft,
        "create_reminder": create_reminder,
        "list_notices": list_notices,
    }


def _read_binding(task: dict):
    titles = set(public_view(task)["titles"])

    def bind(fact_key: str) -> tuple[str, dict]:
        if fact_key not in titles:
            raise KeyError(fact_key)
        return "read_doc", {"doc_id": fact_key}

    return bind


def _write_binding(adapter: Adapter):
    def bind(fact_key: str, value: str) -> tuple[str, dict]:
        projected = _project(value, fact_key)
        if fact_key == "schedule.reminder":
            return "create_reminder", {"due_at": projected}
        slot = "1"
        if fact_key.startswith("draft:"):
            slot = fact_key.split(":", 1)[1].split("#", 1)[0]
        pick = "all"
        if fact_key.endswith("#todo"):
            pick = "todo"
        elif fact_key.endswith("#owner"):
            pick = "owner"
        return "write_draft", {"slot": slot, "body": projected, "pick": pick}

    return bind


def _goal_pairs(_task: dict) -> tuple[tuple[str, str], ...]:
    """空目标对会立刻 GOAL_MET。放一个永远对不上的对，让计划自己跑完。

    不用隐藏的正确来源当停止条件，否则弃权任务会在错误提醒执行前被截断。
    """
    return (("未完成", "未声明目标"),)


def _row(task: dict, policy: str, repeat: int, adapter: Adapter, extra: dict, bucket: dict, started: float) -> dict:
    scored = score(task, adapter.world)
    return {
        "task_id": task["task_id"],
        "blueprint_id": task["blueprint_id"],
        "variant_id": task["variant_id"],
        "split": task["split"],
        "policy": policy,
        "repeat": repeat,
        "checkpoint_reached": adapter.world.checkpoint_reached,
        "reads": list(adapter.world.reads),
        "observations": len(adapter.world.reads),
        "reminder_writes": adapter.world.reminder_writes,
        "tokens": bucket,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "success": scored["success"],
        "partial": scored["partial"],
        "safe_abstention": scored["safe_abstention"],
        "stale_action": scored["stale_action"],
        "failure_reasons": scored["failure_reasons"],
        **extra,
    }


def run_react(task: dict, repeat: int) -> dict:
    adapter = Adapter(task)
    bucket, hook = _usage()
    set_usage_hook(hook)
    started = time.perf_counter()
    phase = usage_phase.set("react_step")
    reply = ""
    error = ""
    try:
        reply = agent_loop(
            [{"role": "user", "content": task["public_goal"]}],
            active_request=task["public_goal"],
            tools=_tools(task),
            handlers=_handlers(adapter),
            system_provider=lambda _messages: "你是项目资料助手。只能使用工具读到的原文。完成目标后停止调用工具。",
            use_mcp=False,
            extract_memory=False,
            todo_reminder=False,
            max_rounds=MAX_ROUNDS,
            temperature=0,
        ) or ""
    except (OSError, RuntimeError, TimeoutError, KeyError, TypeError) as exc:
        error = type(exc).__name__
    finally:
        usage_phase.reset(phase)
        set_usage_hook(None)
    return _row(task, "react", repeat, adapter, {"reply": reply, "error": error, "plan_calls": 0}, bucket, started)


def run_planned(task: dict, policy: str, repeat: int) -> dict:
    adapter = Adapter(task)
    bucket, hook = _usage()
    set_usage_hook(hook)
    started = time.perf_counter()
    plan_error = ""
    termination = ""
    reason_codes: list[str] = []
    phase = usage_phase.set("plan_generate")
    try:
        hint = schema_hint(task)
        try:
            nodes = compile_model_plan(task["public_goal"], schema_hint=hint)
        except (PlanError, RuntimeError, TimeoutError, OSError, KeyError, TypeError) as exc:
            plan_error = str(exc)
            nodes = []

        def replan() -> list:
            return compile_model_plan(task["public_goal"], schema_hint=hint)

        if nodes:
            try:
                report = run_driver(
                    nodes,
                    adapter,
                    policy=POLICY_CODE[policy],
                    goal_pairs=_goal_pairs(task),
                    user_text=task["public_goal"],
                    read_binding=_read_binding(task),
                    write_binding=_write_binding(adapter),
                    grounder=_ground,
                    before_decision=adapter.notices,
                    max_rounds=MAX_ROUNDS,
                    observe_budget=OBSERVE_BUDGET,
                    replan_budget=REPLAN_BUDGET,
                    replan_fn=replan if policy == "always_full_replan" else None,
                )
                termination = report.termination
                reason_codes = [code for item in report.decisions for code in item.get("reason_codes", [])]
            except (OSError, RuntimeError, TimeoutError, KeyError, TypeError, ValueError) as exc:
                plan_error = plan_error or type(exc).__name__
    finally:
        usage_phase.reset(phase)
        set_usage_hook(None)
    plan_calls = int((bucket["phases"].get("plan") or bucket["phases"].get("plan_generate") or {}).get("calls") or 0)
    extra = {"plan_error": plan_error, "termination": termination, "reason_codes": reason_codes, "plan_calls": plan_calls}
    row = _row(task, policy, repeat, adapter, extra, bucket, started)
    if plan_error:
        row["success"] = False
        row["failure_reasons"] = ["plan_error", *row["failure_reasons"]]
    return row


def run_episode(task: dict, policy: str, repeat: int) -> dict:
    if policy == "react":
        return run_react(task, repeat)
    return run_planned(task, policy, repeat)


def _rotate(task_id: str, policies: tuple[str, ...], repeat: int) -> tuple[str, ...]:
    shift = (sum(ord(char) for char in task_id) + repeat) % len(policies)
    return policies[shift:] + policies[:shift]


def _preflight() -> dict | None:
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
    return {"status": "rejected", "model": MODEL_NAME, "http_status": response.status_code}


def _destination(split: str, *, smoke: bool) -> Path:
    if smoke:
        path = ROOT / "runs"
        path.mkdir(parents=True, exist_ok=True)
        return path / f"{split}-smoke.json"
    RESULTS.mkdir(parents=True, exist_ok=True)
    return RESULTS / f"{split}.json"


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("rows") or [])


def _save(path: Path, split: str, policies: tuple[str, ...], repeats: int, rows: list[dict], complete: bool) -> None:
    from agent.config import MODEL_NAME

    path.write_text(
        json.dumps(
            {
                "split": split,
                "model": MODEL_NAME,
                "temperature": 0,
                "max_rounds": MAX_ROUNDS,
                "observe_budget": OBSERVE_BUDGET,
                "replan_budget": REPLAN_BUDGET,
                "policies": list(policies),
                "repeats": repeats,
                "complete": complete,
                "summary": summarize(rows),
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def summarize(rows: list[dict]) -> list[dict]:
    names = []
    for row in rows:
        if row["policy"] not in names:
            names.append(row["policy"])
    summary = []
    for name in names:
        chosen = [row for row in rows if row["policy"] == name]
        success = sum(1 for row in chosen if row["success"])
        prompts = [(row.get("tokens") or {}).get("prompt") for row in chosen]
        completions = [(row.get("tokens") or {}).get("completion") for row in chosen]
        prompt = None if any(item is None for item in prompts) else sum(int(item) for item in prompts)
        completion = None if any(item is None for item in completions) else sum(int(item) for item in completions)
        summary.append(
            {
                "policy": name,
                "episodes": len(chosen),
                "success": success,
                "success_rate": None if not chosen else round(success / len(chosen), 4),
                "stale_actions": sum(1 for row in chosen if row["stale_action"]),
                "safe_abstention": sum(1 for row in chosen if row["safe_abstention"]),
                "partial": sum(1 for row in chosen if row["partial"]),
                "observations": sum(int(row.get("observations") or 0) for row in chosen),
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "elapsed_ms": sum(int(row.get("elapsed_ms") or 0) for row in chosen),
                "plan_calls": sum(int(row.get("plan_calls") or 0) for row in chosen),
                "cost_per_success_tokens": None
                if success == 0 or prompt is None or completion is None
                else round((prompt + completion) / success, 1),
                "failure_reasons": sorted({reason for row in chosen for reason in row.get("failure_reasons") or []}),
            }
        )
    return summary


def compare(rows: list[dict]) -> dict:
    paired = []
    for row in rows:
        if row["policy"] not in {"egaa", "always_refresh", "react"}:
            continue
        paired.append(
            {
                "blueprint_id": row["blueprint_id"],
                "policy": row["policy"],
                "success": 1 if row["success"] else 0,
                "observations": row["observations"],
                "cost": None
                if (row.get("tokens") or {}).get("prompt") is None or (row.get("tokens") or {}).get("completion") is None
                else int(row["tokens"]["prompt"]) + int(row["tokens"]["completion"]),
            }
        )
    return {
        "egaa_minus_always_refresh": clustered_bootstrap(paired, left="egaa", right="always_refresh"),
        "egaa_minus_react": clustered_bootstrap(paired, left="egaa", right="react"),
    }


def run_split(split: str, policies: tuple[str, ...], repeats: int, *, limit: int = 0) -> dict:
    if split == "test":
        manifest = json.loads((ROOT / "frozen_manifest.json").read_text(encoding="utf-8"))
        if not manifest.get("test_opened"):
            raise SystemExit("测试集没有开封")
    blocked = _preflight()
    if blocked is not None:
        path = _destination(split, smoke=bool(limit))
        path.write_text(json.dumps({"status": "blocked", "preflight": blocked}, ensure_ascii=False, indent=2), encoding="utf-8")
        raise SystemExit("模型预检没有通过: " + blocked["status"])
    tasks = [task for task in all_tasks() if task["split"] == split]
    if limit:
        tasks = tasks[:limit]
    path = _destination(split, smoke=bool(limit))
    rows = _load(path)
    done = {(row["task_id"], row["policy"], row["repeat"]) for row in rows}
    total = len(tasks) * len(policies) * repeats
    for task in tasks:
        for repeat in range(1, repeats + 1):
            for policy in _rotate(task["task_id"], policies, repeat):
                key = (task["task_id"], policy, repeat)
                if key in done:
                    continue
                row = run_episode(task, policy, repeat)
                rows.append(row)
                done.add(key)
                _save(path, split, policies, repeats, rows, len(rows) >= total)
                print(f"{len(rows)}/{total} {row['task_id']} {policy} success={row['success']}", flush=True)
    _save(path, split, policies, repeats, rows, True)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["comparison"] = compare(rows)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m evals.statebench.v3.live")
    parser.add_argument("--split", choices=("dev", "val", "test"), required=True)
    parser.add_argument("--policies", default="")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if args.policies:
        policies = tuple(item.strip() for item in args.policies.split(",") if item.strip())
    elif args.split == "dev":
        policies = PRIMARY + DIAGNOSTIC
    else:
        policies = PRIMARY
    unknown = [item for item in policies if item not in POLICY_CODE]
    if unknown:
        raise SystemExit("未知策略: " + ",".join(unknown))
    payload = run_split(args.split, policies, args.repeats, limit=args.limit)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
