"""从原始回合记录汇总指标。分母为空时保留不适用，不写成 0。"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


POLICY_NAMES = {
    "B0": "脚本化 ReAct 循环基线",
    "B1": "已验证计划",
    "B2": "证据门控策略",
    "B3": "每次写前刷新",
    "B4": "通知触发全量重规划",
}


def _ratio(numerator: int, denominator: int) -> str | float:
    if denominator <= 0:
        return "not_applicable"
    return numerator / denominator


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["policy"])].append(row)
    policies: dict[str, Any] = {}
    for policy, items in grouped.items():
        successes = [item for item in items if item["score"]["goal_met"]]
        stale = sum(int(item["score"]["stale_source_writes"]) for item in items)
        evidence_actions = sum(int(item.get("evidence_actions") or 0) for item in items)
        replans = [entry for item in items for entry in item.get("replans") or []]
        justified = sum(1 for entry in replans if entry.get("justified"))
        false_values = [item["score"]["false_invalidations"] for item in items]
        if any(value != "not_applicable" for value in false_values):
            false_metric: str | float = sum(int(value) for value in false_values if value != "not_applicable")
        else:
            false_metric = "not_applicable"
        tool_calls = sum(int(item.get("tool_calls") or 0) for item in items)
        violations = sum(1 for item in items if not all(item["score"].get("constraint_checks") or [True]))
        budget_stops = sum(1 for item in items if str(item.get("termination_reason")) in {"OBSERVE_BUDGET", "REPLAN_BUDGET", "MAX_ROUNDS"})
        policies[policy] = {
            "name": POLICY_NAMES.get(policy, policy),
            "tasks": len(items),
            "successes": len(successes),
            "success_rate": _ratio(len(successes), len(items)),
            "stale_actions": stale,
            "evidence_actions": evidence_actions,
            "stale_action_rate": _ratio(stale, evidence_actions),
            "false_invalidations": false_metric,
            "replans": len(replans),
            "unnecessary_replans": len(replans) - justified,
            "unnecessary_replan_rate": _ratio(len(replans) - justified, len(replans)),
            "tool_calls": tool_calls,
            "tool_calls_per_success": "undefined" if not successes else tool_calls / len(successes),
            "model_cost_per_success": "not_applicable",
            "degrade_count": sum(int(item.get("degrade_count") or 0) for item in items),
            "constraint_violations": violations,
            "constraint_violation_rate": _ratio(violations, len(items)),
            "unverified_effect_count": sum(int(item.get("unverified_effect_count") or 0) for item in items),
            "recovery_stop_count": sum(int(item.get("recovery_stop_count") or 0) for item in items),
            "observe_count": sum(int(item.get("observe_count") or 0) for item in items),
            "decision_count": sum(int(item.get("decision_count") or 0) for item in items),
            "budget_stops": budget_stops,
            "token_usage": 0,
            "token_usage_note": "mock 脚本模拟，用量记 0",
        }
    return {"policies": policies}


def scene_summaries(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scenes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        scenes[str(row.get("scene") or "unknown")].append(row)
    return {scene: summarize(items) for scene, items in sorted(scenes.items())}


def observation_sequences(rows: list[dict[str, Any]], policy: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for row in rows:
        if row["policy"] != policy:
            continue
        found[str(row["task_id"])] = [
            f"{item['decision_kind']}:{','.join(item['reason_codes'])}"
            for item in row.get("decisions") or []
            if item.get("decision_kind") == "OBSERVE"
        ]
    return found


def sequences_match(rows: list[dict[str, Any]], left: str = "B2", right: str = "B3") -> bool:
    first = observation_sequences(rows, left)
    second = observation_sequences(rows, right)
    if not first or set(first) != set(second):
        return False
    return all(first[task_id] == second[task_id] for task_id in first)
