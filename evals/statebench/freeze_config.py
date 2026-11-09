"""只在验证集上选择事先写明的一个风险候选，然后冻结。"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from evals.statebench.catalog import load_splits
from evals.statebench.metrics import summarize
from evals.statebench.protocol import (
    FROZEN_PATH,
    budget_of,
    contract_hashes,
    load_experiment,
    risk_rule,
)
from evals.statebench.runner import run_split

SELECTION_RULE = (
    "验证集任务成功率较高者胜出；相同则观察次数较少者胜出；"
    "仍相同则取 before_irreversible。主预算下至少 4 条因预算停止时，"
    "改用观察预算 4 并在验证集上重选一次。"
)


def _rank(rows: list[dict[str, Any]]) -> tuple[int, int]:
    summary = summarize(rows)["policies"]
    merged = {"successes": 0, "observe_count": 0, "budget_stops": 0}
    for item in summary.values():
        merged["successes"] += int(item["successes"])
        merged["observe_count"] += int(item["observe_count"])
        merged["budget_stops"] += int(item["budget_stops"])
    return merged["successes"], merged["observe_count"], merged["budget_stops"]


def _better(left: str, right: str, results: dict[str, list[dict[str, Any]]]) -> str:
    left_rank = _rank(results[left])
    right_rank = _rank(results[right])
    if left_rank[0] != right_rank[0]:
        return left if left_rank[0] > right_rank[0] else right
    if left_rank[1] != right_rank[1]:
        return left if left_rank[1] < right_rank[1] else right
    return "before_irreversible"


def _age_report(rows: list[dict[str, Any]]) -> dict[str, int | bool]:
    ages = [age for row in rows for age in row.get("ages") or []]
    triggered = sum(1 for age in ages if age >= 10)
    return {
        "max_age_seen": max(ages) if ages else 0,
        "trigger_count": triggered,
        "triggered": triggered > 0,
        "samples": len(ages),
    }


def select_on_validation() -> dict[str, Any]:
    experiment = load_experiment()
    primary = budget_of(experiment)
    test_ids = set(load_splits()["test"])
    val_ids = set(load_splits()["val"])
    results: dict[str, list[dict[str, Any]]] = {}
    for mode in ("before_irreversible", "evidence_age"):
        results[mode] = run_split(
            "val",
            ("B2",),
            risk=risk_rule(experiment, mode),
            observe_budget=primary["observe"],
        )
    winner = _better("before_irreversible", "evidence_age", results)
    observe_budget = primary["observe"]
    fallback_used = False
    if _rank(results[winner])[2] >= 4:
        fallback_used = True
        observe_budget = primary["observe_fallback"]
        for mode in ("before_irreversible", "evidence_age"):
            results[mode] = run_split(
                "val",
                ("B2",),
                risk=risk_rule(experiment, mode),
                observe_budget=observe_budget,
            )
        winner = _better("before_irreversible", "evidence_age", results)
    logged_ids = {row["task_id"] for rows in results.values() for row in rows}
    if logged_ids & test_ids:
        raise RuntimeError("选择日志混入了测试集")
    if not logged_ids <= val_ids:
        raise RuntimeError("选择过程使用了验证集以外的任务")
    ages = _age_report(results["evidence_age"])
    config = {
        "schema": "statebench-frozen-config-v1",
        "selected_on": "val",
        "risk_mode": winner,
        "max_age": 10 if winner == "evidence_age" else None,
        "observe_budget": observe_budget,
        "replan_budget": primary["replan"],
        "max_tool_calls": primary["tools"],
        "max_rounds": primary["rounds"],
        "temperature": experiment.get("temperature"),
        "fallback_used": fallback_used,
        "selection_rule": SELECTION_RULE,
        "evidence_age": ages,
        "human_review": "PENDING",
        "comparison_baseline": "scripted_react_loop",
        "model_cost": "not_applicable",
        "logged_task_ids": sorted(logged_ids),
        **contract_hashes(),
    }
    if not ages["triggered"]:
        config["evidence_age_note"] = "evidence_age=10 在验证集的决策时域内没有出现 age>=10，不能把未触发解释成风险控制发挥了作用。"
    FROZEN_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.statebench.freeze_config")
    parser.add_argument("--mock", action="store_true")
    args = parser.parse_args(argv)
    if not args.mock:
        print("冻结选择只接受 --mock。", file=sys.stderr)
        return 2
    config = select_on_validation()
    print(json.dumps({"risk_mode": config["risk_mode"], "observe_budget": config["observe_budget"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
