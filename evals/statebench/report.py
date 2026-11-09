"""冻结测试的主表。Mock 成本是工具调用，模型费用不适用。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from agent.algorithms.types import RiskRule
from evals.statebench.catalog import load_task
from evals.statebench.execute import run_controlled
from evals.statebench.metrics import POLICY_NAMES, scene_summaries, summarize
from evals.statebench.protocol import frozen_risk, load_frozen
from evals.statebench.runner import run_split
from evals.statebench.statistics import clustered_paired_delta, describe_scripted_comparison
from evals.statebench.traces import read_jsonl

ROOT_REPORT = Path(__file__).resolve().parent


def _pairs(rows: list[dict[str, Any]]) -> dict[str, list[tuple[bool, bool]]]:
    by_task: dict[str, dict[str, bool]] = defaultdict(dict)
    clusters: dict[str, str] = {}
    for row in rows:
        by_task[row["task_id"]][row["policy"]] = bool(row["score"]["goal_met"])
        clusters[row["task_id"]] = str(row.get("blueprint_id") or row["task_id"])
    grouped: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    for task_id, item in by_task.items():
        if "B0" in item and "B2" in item:
            grouped[clusters[task_id]].append((item["B0"], item["B2"]))
    return grouped


def _demo_lines(rows: list[dict[str, Any]]) -> list[str]:
    lines = ["## 三条演示", ""]
    s1 = next(row for row in rows if row["policy"] == "B2" and row.get("scene") == "S1")
    writes = [name for name in s1["tool_names"] if name == "write_fact"]
    lines.append(
        f"相关变化: {s1['task_id']} 的证据门控策略在读取之后继续观察，write_fact 次数为 {len(writes)}。"
        f"世界目标为 {s1['score']['goal_met']}。修复记录含 {', '.join(s1.get('repair_kinds') or ['无'])}。"
    )
    hidden = run_controlled(load_task("s3_meeting_a"), "B2", risk=RiskRule("evidence_age", 10), observe_budget=3)
    agent_text = "\n".join(
        json.dumps(item, ensure_ascii=False) for item in read_jsonl(Path(hidden["trace_dir"]) / "agent_trace.jsonl")
    )
    leaked = "16:00" in agent_text
    lines.append(
        "没有新观察时的隐藏变化: 用 evidence_age=10 跑 s3_meeting_a，决策时域内年龄达不到 10，因此不会为了隐藏变化主动再读。"
        f"信念侧目标为 {hidden['goal_verified_final']}，世界目标为 {hidden['score']['goal_met']}。"
        f"Agent 轨迹{'出现' if leaked else '没有出现'}隐藏新值。"
    )
    lines.append(
        "未验证写入: 写入动作只在 resolve_args 能从当前 VALID 证据取值之后发出。"
        "本地参数拒绝不计入工具调用。评分器不参与中途的 goal_verified。"
    )
    lines.append("")
    return lines


def render(rows: list[dict[str, Any]], config: dict[str, Any]) -> str:
    summary = summarize(rows)
    scenes = scene_summaries(rows)
    interval = clustered_paired_delta(_pairs(rows), rounds=2000, seed=0)
    wording = describe_scripted_comparison(interval)
    lines = [
        "# D14 冻结测试记录",
        "",
        "比较对象是脚本化 ReAct 循环。模型费用不适用。人工任务语义复核保持 PENDING。",
        "这 40 条是受控模板实例，其中 note 蓝图存在结构重复，不能写成 40 种任务。",
        "",
        wording,
        "",
        f"蓝图样本 {interval['n_blueprints']}，任务样本 {interval['n']}，"
        f"成功率差 {interval['delta']:.4f}，区间 [{interval['low']:.4f}, {interval['high']:.4f}]。",
        "",
        f"冻结规则: {config['risk_mode']}，观察预算 {config['observe_budget']}，重规划预算 {config['replan_budget']}。",
        str(config.get("evidence_age_note") or "证据年龄候选的触发情况见冻结配置。"),
        "",
    ]
    b2 = summary["policies"]["B2"]
    b3 = summary["policies"]["B3"]
    if b2["tool_calls"] == b3["tool_calls"] and b2["successes"] == b3["successes"]:
        lines.append(
            "证据门控策略和每次写前刷新的任务成功率与工具调用数相同。"
            "原因码一个是写入前的风险观察，一个是每次刷新。这次不能把选择性观察写成更省调用。"
        )
        lines.append("")
    lines.append("## 主表")
    lines.append("")
    for policy in ("B0", "B1", "B2", "B3", "B4"):
        item = summary["policies"][policy]
        lines.append(f"### {policy} {POLICY_NAMES[policy]}")
        lines.append("")
        lines.append(f"任务成功率: {item['successes']}/{item['tasks']}")
        lines.append(f"过期行动: {item['stale_actions']}/{item['evidence_actions']}")
        lines.append(f"误失效率: {item['false_invalidations']}")
        lines.append(f"无谓重规划: {item['unnecessary_replan_rate']}（次数 {item['replans']}）")
        lines.append(f"每成功工具调用: {item['tool_calls_per_success']}")
        lines.append(f"降级次数: {item['degrade_count']}")
        lines.append(f"硬约束违反: {item['constraint_violations']}/{item['tasks']}")
        lines.append(f"未确认副作用: {item['unverified_effect_count']}")
        lines.append(f"恢复停止: {item['recovery_stop_count']}")
        lines.append("模型费用: 不适用")
        lines.append("Token 用量: 0，脚本模拟")
        lines.append("")
    lines.append("## 场景分组")
    lines.append("")
    for scene, scene_summary in scenes.items():
        lines.append(f"### {scene}")
        lines.append("")
        for policy in ("B0", "B1", "B2", "B3", "B4"):
            item = scene_summary["policies"][policy]
            lines.append(f"- {POLICY_NAMES[policy]}: {item['successes']}/{item['tasks']}，工具 {item['tool_calls']}，观察 {item['observe_count']}")
        lines.append("")
    lines.extend(_demo_lines(rows))
    lines.extend(
        [
            "## 复现",
            "",
            "```text",
            "python -m evals.statebench.runner --split dev --mock",
            "python -m evals.statebench.freeze_config --mock",
            "python -m evals.statebench.report --mock",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.statebench.report")
    parser.add_argument("--mock", action="store_true")
    args = parser.parse_args(argv)
    if not args.mock:
        print("正式表格只接受 --mock。", file=sys.stderr)
        return 2
    config = load_frozen()
    frozen_risk(config)
    rows = run_split("test")
    text = render(rows, config)
    report_path = ROOT_REPORT / "d14_report.md"
    table_path = ROOT_REPORT / "d14_table.json"
    report_path.write_text(text, encoding="utf-8")
    table_path.write_text(json.dumps({"config": config, "rows": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
