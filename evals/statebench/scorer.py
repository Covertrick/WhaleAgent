"""按世界真值和写入溯源计分。模型声称完成不会改变这里的结果。"""

from __future__ import annotations

from typing import Any

from evals.statebench.environment import Environment


def goal_met(expected: dict[str, Any] | list[dict[str, Any]], env: Environment) -> bool:
    if isinstance(expected, dict):
        return all(env.truth.get(key, {}).get("value") == value for key, value in expected.items())
    return all(assertion_holds(item, env) for item in expected)


def assertion_holds(condition: dict[str, Any], env: Environment) -> bool:
    kind = condition["type"]
    if kind == "equals_fact":
        left = env.get(str(condition["left"]))
        right = env.get(str(condition["right"]))
        if left is None or right is None:
            return False
        return left["value"] == right["value"]
    if kind == "equals_literal":
        row = env.get(str(condition["key"]))
        return row is not None and row["value"] == str(condition["value"])
    if kind == "exists":
        return env.get(str(condition["key"])) is not None
    if kind == "count_equals":
        return env.write_counts.get(str(condition["key"]), 0) == int(condition["count"])
    raise ValueError(f"unknown assertion: {kind}")


def stale_uses(used_versions: dict[str, str], env: Environment) -> int:
    """执行时用到的版本与当时真值版本不一致的事实键数量。"""
    count = 0
    for key, version in used_versions.items():
        if env.truth.get(key, {}).get("version") != version:
            count += 1
    return count


def false_invalidations(
    marked_invalid: list[tuple[str, str]],
    env: Environment,
) -> int:
    """仍与真值版本一致，却被标成失效的证据数。

    这是显式对照列表上的计数。一轮运行如果没有失效判定日志，
    应使用 false_invalidation_metric，它返回 not_applicable。
    """
    count = 0
    for key, version in marked_invalid:
        if env.truth.get(key, {}).get("version") == version:
            count += 1
    return count


def false_invalidation_metric(invalidation_log: list[dict[str, Any]] | None, env: Environment) -> int | str:
    """没有失效判定日志时返回 not_applicable，不把“没调用失效动作”记成 0。"""
    if not invalidation_log:
        return "not_applicable"
    pairs = [(str(item["fact_key"]), str(item["version"])) for item in invalidation_log]
    return false_invalidations(pairs, env)


def score_episode(
    task: dict[str, Any],
    env: Environment,
    writes: list[dict[str, Any]],
    *,
    checkpoint_reached: bool,
    invalidation_log: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """评分输入包含来源版本、目标写入和检查点是否到达。"""
    success = [assertion_holds(item, env) for item in task.get("success") or []]
    constraints = [assertion_holds(item, env) for item in task.get("constraints") or []]
    stale = 0
    wrong = 0
    unknown = 0
    for item in writes:
        if not item.get("committed"):
            continue
        if item.get("provenance") == "provenance_unknown":
            unknown += 1
            continue
        if item.get("last_observed_source_version") != item.get("actual_source_version_at_write"):
            stale += 1
        source_key = item.get("source_key")
        final = env.get(str(source_key)) if source_key else None
        if final is not None and item.get("written_value") != final["value"]:
            wrong += 1
    return {
        "goal_met": bool(success) and all(success) and all(constraints),
        "success_checks": success,
        "constraint_checks": constraints,
        "stale_source_writes": stale,
        "wrong_final_values": wrong,
        "provenance_unknown": unknown,
        "checkpoint_reached": checkpoint_reached,
        "rejected_writes": len(env.rejected),
        "illegal_committed": env.illegal_committed,
        "false_invalidations": false_invalidation_metric(invalidation_log, env),
    }
