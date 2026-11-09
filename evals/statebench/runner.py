"""离线步进和分片运行。B0 走原循环，B1–B4 走同一环境和评分器。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agent.algorithms.controller import decide
from agent.algorithms.types import BeliefState, DecideContext, PlanNode
from evals.statebench.b0 import run_b0
from evals.statebench.catalog import load_splits, load_task
from evals.statebench.environment import Environment
from evals.statebench.execute import run_controlled
from evals.statebench.metrics import sequences_match, summarize
from evals.statebench.protocol import frozen_risk, load_frozen

ROOT = Path(__file__).resolve().parent
POLICIES = ("B0", "B1", "B2", "B3", "B4")


def notices_for(env: Environment, checkpoint: str) -> tuple[str, ...]:
    return tuple(env.apply_checkpoint(checkpoint))


def step(
    belief: BeliefState,
    nodes: list[PlanNode],
    ctx: DecideContext,
):
    return decide(belief, nodes, ctx)


def run_policy(task_id: str, policy: str, *, risk=None, observe_budget: int | None = None) -> dict[str, Any]:
    task = load_task(task_id)
    if policy == "B0":
        result = run_b0(task_id, llm="mock", task=task)
        env = result.pop("env", None)
        if env is not None:
            env.close()
        result.pop("writes", None)
        result.pop("messages", None)
        result.pop("decision_inputs", None)
        result.pop("text", None)
        return result
    return run_controlled(task, policy, risk=risk, observe_budget=observe_budget)


def run_split(
    split: str,
    policies: tuple[str, ...] = POLICIES,
    *,
    risk=None,
    observe_budget: int | None = None,
) -> list[dict[str, Any]]:
    if split == "test":
        config = load_frozen()
        risk = frozen_risk(config)
        observe_budget = int(config["observe_budget"])
    rows = []
    for task_id in load_splits()[split]:
        for policy in policies:
            rows.append(run_policy(task_id, policy, risk=risk, observe_budget=observe_budget))
    if split == "dev":
        _write_dev_index(rows)
    return rows


def _write_dev_index(rows: list[dict[str, Any]]) -> None:
    summary = summarize(rows)
    same = sequences_match(rows)
    lines = [
        "# 开发集运行索引",
        "",
        "这是原始轨迹索引，不是正式成功率。",
        "",
        f"策略观察序列是否完全一致: {'POLICY_NOT_DISTINGUISHABLE' if same else '序列不同'}",
        "",
    ]
    if same:
        lines.append("开发集上 B2 与 B3 的观察决策序列完全一致，不能把选择性观察写成更省调用。")
        lines.append("")
    b2_reads = sum(item.get("observe_count", 0) for item in rows if item["policy"] == "B2")
    b3_reads = sum(item.get("observe_count", 0) for item in rows if item["policy"] == "B3")
    if b2_reads == b3_reads:
        lines.append("开发集上 B2 与 B3 的观察计数相同。工具次数相同的时候，不能单独把原因码差异写成成本优势。")
        lines.append("")
    for policy, item in summary["policies"].items():
        lines.append(f"## {policy} {item['name']}")
        lines.append("")
        lines.append(f"完成任务: {item['tasks']}")
        lines.append(f"世界目标达成: {item['successes']}")
        lines.append(f"工具调用: {item['tool_calls']}")
        lines.append(f"观察计数: {item['observe_count']}")
        lines.append(f"重规划: {item['replans']}")
        lines.append(f"降级: {item['degrade_count']}")
        lines.append(f"模型费用: 不适用")
        lines.append("")
    lines.append("## 轨迹")
    lines.append("")
    for row in rows:
        lines.append(f"- {row['policy']} {row['task_id']}: {row['trace_dir']}")
    path = ROOT / "dev_run_index.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.statebench.runner")
    parser.add_argument("--split", required=True, choices=("dev", "val", "test"))
    parser.add_argument("--mock", action="store_true")
    args = parser.parse_args(argv)
    if not args.mock:
        print("这一入口只接受 --mock。Live 对照另开，不混入这张表。", file=sys.stderr)
        return 2
    if args.split == "test":
        try:
            load_frozen()
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    rows = run_split(args.split)
    out = ROOT / "runs" / f"{args.split}_rows.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)
    print(json.dumps(summarize(rows), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
