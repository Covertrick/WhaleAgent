"""试验蓝图只检查结构和泄漏，不调用模型。"""

from __future__ import annotations

import unittest

from evals.statebench.v3.blueprints import BLUEPRINTS, HIDDEN, all_instances, audit_rows, visible_task


class V3TrialTests(unittest.TestCase):
    def test_twelve_structures_are_not_value_swaps(self) -> None:
        self.assertEqual(len(BLUEPRINTS), 12)
        shapes = {item.dag_shape for item in BLUEPRINTS}
        self.assertEqual(shapes, {"parallel", "fanout", "chain", "join"})
        scenarios = sorted(item.scenario for item in BLUEPRINTS)
        self.assertEqual(scenarios, ["S0", "S0", "S1", "S1", "S2", "S2", "S3", "S3", "S4", "S4", "S5", "S5"])
        identities = {(item.scenario, item.dag_shape, item.goal_structure) for item in BLUEPRINTS}
        self.assertEqual(len(identities), 12)

    def test_variants_change_the_text_and_hide_the_score(self) -> None:
        seen: set[str] = set()
        for task in all_instances():
            self.assertNotIn(task["prompt"], seen)
            seen.add(task["prompt"])
            public = {
                "task_id": task["task_id"],
                "prompt": task["prompt"],
                "tool_schemas": task["tool_schemas"],
                "branches": (task["dag_shape"], task["scenario"]),
            }
            view = visible_task(public)
            self.assertTrue(HIDDEN.isdisjoint(view))
            self.assertNotIn(task["expected_behavior"], task["prompt"])
            with self.assertRaises(ValueError):
                visible_task(task)
        self.assertEqual(len(seen), 24)
        self.assertEqual(len(audit_rows()), 24)
        self.assertTrue(all(row["third_party"] == "no" for row in audit_rows()))
