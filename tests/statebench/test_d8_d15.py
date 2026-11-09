"""执行器不把世界评分回传给决策器，并留下可检查的轨迹。"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.algorithms.types import RiskRule
from evals.statebench.catalog import load_splits, load_task
from evals.statebench.execute import run_controlled
from evals.statebench.protocol import load_experiment, risk_rule
from evals.statebench.scorer import score_episode
from evals.statebench.statistics import clustered_paired_delta, describe_scripted_comparison
from evals.statebench.traces import read_jsonl


class ExecutorTests(unittest.TestCase):
    def test_s1_reobserves_and_scores_after_the_loop(self) -> None:
        with patch("evals.statebench.execute.score_episode", wraps=score_episode) as scored:
            result = run_controlled(load_task("s1_meeting_a"), "B2")
        self.assertEqual(scored.call_count, 1)
        self.assertTrue(result["score"]["goal_met"])
        self.assertEqual(result["tool_names"].count("write_fact"), 1)
        self.assertEqual(result["goal_verified_final"], True)
        self.assertIn("evidence_refresh", result["repair_kinds"])
        self.assertIn("parameter_rebind", result["repair_kinds"])
        read_done = True
        for item in result["decisions"]:
            if item["decision_kind"] == "CONTINUE" and "write" in item["target_nodes"]:
                read_done = "read" not in item["target_nodes"]
        self.assertTrue(read_done)

    def test_s3_hidden_value_does_not_enter_the_agent_trace(self) -> None:
        result = run_controlled(
            load_task("s3_meeting_a"),
            "B2",
            risk=RiskRule("evidence_age", 10),
        )
        agent = "\n".join(
            str(item) for item in read_jsonl(Path(result["trace_dir"]) / "agent_trace.jsonl")
        )
        self.assertNotIn("16:00", agent)
        self.assertTrue(result["goal_verified_final"])
        self.assertFalse(result["score"]["goal_met"])
        self.assertTrue(all(age < 10 for age in result["ages"]))

    def test_b4_replans_the_same_notice_once(self) -> None:
        result = run_controlled(load_task("s1_meeting_a"), "B4")
        replans = [
            item for item in result["decisions"] if "ANY_NOTICE" in item["reason_codes"]
        ]
        self.assertEqual(len(replans), 1)
        self.assertTrue(result["score"]["goal_met"])

    def test_observe_budget_is_checked_before_the_read(self) -> None:
        result = run_controlled(load_task("s0_meeting_a"), "B2", observe_budget=0)
        self.assertEqual(result["termination_reason"], "OBSERVE_BUDGET")
        self.assertEqual(result["tool_calls"], 0)
        self.assertEqual(result["rejected_local"], 0)

    def test_candidates_are_the_two_predeclared_rules(self) -> None:
        experiment = load_experiment()
        self.assertEqual(risk_rule(experiment, "before_irreversible").mode, "before_irreversible")
        self.assertEqual(risk_rule(experiment, "evidence_age").max_age, 10)

    def test_zero_interval_names_the_scripted_baseline(self) -> None:
        result = clustered_paired_delta({"bp": [(True, True), (False, False)]}, rounds=50, seed=1)
        text = describe_scripted_comparison(result)
        self.assertIn("没有稳定差异", text)
        self.assertIn("脚本化", text)
        self.assertNotIn("等效", text)

    def test_statebench_does_not_import_channel(self) -> None:
        root = Path(__file__).resolve().parents[2] / "evals" / "statebench"
        offenders: list[str] = []
        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [item.name for item in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                if any(name.startswith("agent.channel") or name == "channel" for name in names):
                    offenders.append(path.name)
        self.assertEqual(offenders, [])
        self.assertTrue(load_splits()["dev"])


if __name__ == "__main__":
    unittest.main()
