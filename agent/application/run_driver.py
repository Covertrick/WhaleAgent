"""外层决策循环。这里不调用 agent_loop，也不另开一次 Run。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from agent.algorithms.controller import acknowledgement_allowed, acknowledge, decide
from agent.algorithms.evidence import apply_observation
from agent.algorithms.planner import ResolveError, resolve_args
from agent.algorithms.repair import repair_plan
from agent.algorithms.types import BeliefState, ChangeNotice, DecideContext, PlanNode, RiskRule
from agent.application.catalog import read_call, write_call
from agent.application.effects import effect_status
from agent.application.evidence_codec import evidence_from_tool
from agent.application.goal_verifier import goal_report

REFRESH_REASONS = {"ALWAYS_REFRESH", "POTENTIALLY_STALE", "FACT_CHANGED", "UNKNOWN_SCOPE", "MISSING_EVIDENCE"}
LABELS = {
    "note.draft": "待办草稿",
    "schedule.reminder": "截止提醒",
    "project.materials": "会议资料",
    "project.deadline": "截止时间",
}


@dataclass
class DriverResult:
    reply: str
    run_id: str
    decisions: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    termination: str = ""
    goal_verified: bool = False
    confirmed: list[str] = field(default_factory=list)
    needs_confirmation: list[str] = field(default_factory=list)
    observe_count: int = 0
    policy: str = "B2"
    policy_name: str = "egaa"
    policy_version: str = "1"


def run_driver(
    nodes: list[PlanNode],
    executor,
    *,
    policy: str = "B2",
    goal_pairs: tuple[tuple[str, str], ...] = (),
    user_text: str = "",
    visible_facts: dict[str, dict[str, str]] | None = None,
    before_decision: Callable[[int, list[PlanNode]], list[ChangeNotice]] | None = None,
    risk: RiskRule | None = None,
    observe_budget: int = 6,
    replan_budget: int = 2,
    max_rounds: int = 10,
    read_binding: Callable[[str], tuple[str, dict]] | None = None,
    write_binding: Callable[[str, str], tuple[str, dict]] | None = None,
    grounder: Callable[..., object] | None = None,
) -> DriverResult:
    from agent.engine.runner import run_engine
    from agent.policies.egaa import EGAAPolicy

    agent = EGAAPolicy(
        nodes,
        policy=policy,
        goal_pairs=goal_pairs,
        visible_facts=visible_facts,
        before_decision=before_decision,
        risk=risk,
        observe_budget=observe_budget,
        replan_budget=replan_budget,
        read_binding=read_binding or read_call,
        write_binding=write_binding or write_call,
        grounder=grounder,
    )
    _freeze_policy(agent.policy_name, agent.policy_version)
    engine = run_engine(agent, executor, max_rounds=max_rounds)
    verified, confirmed, open_items = goal_report(agent.belief, agent.receipts, goal_pairs)
    needs = list(open_items)
    termination = agent.termination or engine.termination
    if termination == "UNVERIFIED" and "schedule.reminder" not in needs:
        needs.append("schedule.reminder")
    result = DriverResult(
        reply=_reply(user_text, verified, confirmed, needs, agent.decisions, termination),
        run_id=_current_run_id(),
        decisions=agent.decisions,
        tool_calls=[{"tool": item["tool"], "arguments": item["arguments"]} for item in engine.tool_calls],
        termination=termination,
        goal_verified=verified,
        confirmed=confirmed,
        needs_confirmation=needs,
        observe_count=agent.observes_used,
        policy=policy,
        policy_name=agent.policy_name,
        policy_version=agent.policy_version,
    )
    _write_sidecar(result)
    return result


def _observe(executor, belief: BeliefState, fact_key: str, now: int, facts: dict, tool_calls: list[dict]):
    try:
        tool, arguments = read_call(fact_key)
    except KeyError:
        return None
    content = _execute(executor, tool, arguments, tool_calls)
    fallback = facts.get(fact_key) or {}
    item = evidence_from_tool(
        fact_key=fact_key,
        content=content,
        observed_at=now,
        fallback_version=fallback.get("source_version"),
        fallback_value=fallback.get("value"),
        fallback_uri=fallback.get("source_uri") or "",
    )
    if effect_status(content) == "FAILED" and not fallback:
        return None
    return apply_observation(belief, item)


def _observed_status(content: str, tool: str) -> str:
    """账本已经写成 UNKNOWN 时，口语回执不能当成成功。"""
    status = effect_status(content)
    from agent.harness.runtime import current_run

    run = current_run()
    if run is None:
        return status
    for intent in reversed(run.intents):
        if intent.skill != tool:
            continue
        if intent.status == "unknown":
            return "UNVERIFIED"
        if intent.status == "failed":
            return "FAILED"
        break
    return status


def _execute(executor, name: str, arguments: dict, tool_calls: list[dict]) -> str:
    tool_calls.append({"tool": name, "arguments": arguments})
    if hasattr(executor, "bind_call"):
        executor.bind_call(f"app-{len(tool_calls)}")
    result = executor.execute(name, arguments)
    if isinstance(result, dict):
        return str(result.get("content") or "")
    return str(result)


def _node(nodes: list[PlanNode], targets: tuple[str, ...]) -> PlanNode | None:
    if not targets:
        return None
    for node in nodes:
        if node.id == targets[0]:
            return node
    return None


def _unverified_facts(nodes: list[PlanNode], unverified: list[str]) -> set[str]:
    wanted = set(unverified)
    return {str(node.args.get("fact_key") or "") for node in nodes if node.id in wanted}


def _freeze_policy(name: str, version: str) -> None:
    """有打开的 Run 时把策略写进账本。没有 Run 的离线调用保持原样。"""
    from agent.harness.runtime import current_run, get_runtime

    run = current_run()
    if run is None:
        return
    get_runtime().bind_policy(run, name, version)


def _current_run_id() -> str:
    from agent.harness.runtime import current_run

    run = current_run()
    return run.run_id if run is not None else ""


def _write_sidecar(result: DriverResult) -> None:
    if not result.run_id:
        return
    from agent.harness.store import harness_root

    path = harness_root() / "decisions" / f"{result.run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": result.run_id,
        "policy": result.policy,
        "policy_name": result.policy_name,
        "policy_version": result.policy_version,
        "termination": result.termination,
        "goal_verified": result.goal_verified,
        "decisions": result.decisions,
        "tool_calls": result.tool_calls,
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _reply(
    user_text: str,
    verified: bool,
    confirmed: list[str],
    needs: list[str],
    decisions: list[dict],
    termination: str,
) -> str:
    _ = user_text
    lines = ["项目资料协同做完了这一轮。"]
    if confirmed:
        lines.append("已确认：" + "、".join(LABELS.get(item, item) for item in confirmed) + "。")
    if needs:
        lines.append("还需要你确认：" + "、".join(LABELS.get(item, item) for item in needs) + "。")
    if termination == "UNVERIFIED":
        lines.append("提醒那一步没有拿到确认回执，我没有再创建一次。")
    elif termination == "WRITE_FAILED":
        lines.append("有一步写入没有完成，我没有把它当成成功。")
    elif not verified and termination in {"OBSERVE_BUDGET", "RESOLVE_FAILED", "EVIDENCE_UNKNOWN"}:
        lines.append("有的资料无法核对来源，或来源互相冲突，我没有拿它去做不可逆操作。")
    elif verified:
        lines.append("草稿和提醒都对上了当前仍有效的证据。")
    reasons = [code for item in decisions for code in item["reason_codes"]]
    if reasons:
        lines.append("决策原因：" + " → ".join(reasons) + "。")
    return "\n".join(lines)


def load_decisions(run_id: str) -> list[dict]:
    from agent.harness.store import harness_root

    path = Path(harness_root()) / "decisions" / f"{run_id}.json"
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return list(payload.get("decisions") or [])
