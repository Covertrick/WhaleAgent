"""v3 数据集只做离线审计，不调用模型。"""

from __future__ import annotations

import unittest

from agent.algorithms.types import PlanNode
from agent.policies.planning import local_or_full_update
from evals.statebench.v3.audit import audit_rows
from evals.statebench.v3.catalog import DEV_IDS, SPECS, all_tasks
from evals.statebench.v3.statistics import clustered_bootstrap


class V3DatasetTests(unittest.TestCase):
    def test_forty_eight_blueprints_and_pending_review(self) -> None:
        rows = audit_rows()
        self.assertEqual(len(SPECS), 48)
        self.assertEqual(len(all_tasks()), 96)
        self.assertEqual(len(rows), 96)
        self.assertEqual({spec.split for spec in SPECS}, {"dev", "val", "test"})
        self.assertEqual({spec.blueprint_id for spec in SPECS if spec.split == "dev"}, set(DEV_IDS))
        self.assertTrue(all(row["human_review"] == "HUMAN_REVIEW_PENDING" for row in rows))
        self.assertTrue(all(row["notes"] == "" for row in rows))
        shapes = {spec.scenario: {item.dag_shape for item in SPECS if item.scenario == spec.scenario} for spec in SPECS}
        for scenario, found in shapes.items():
            self.assertEqual(found, {"parallel", "fanout", "chain", "join"}, scenario)

    def test_bootstrap_self_check_is_not_an_experiment(self) -> None:
        rows = []
        for index in range(6):
            blueprint = f"b{index // 2}"
            rows.append({"blueprint_id": blueprint, "policy": "egaa", "success": 1, "observations": 1, "cost": 2})
            rows.append({"blueprint_id": blueprint, "policy": "always_refresh", "success": 1, "observations": 3, "cost": 4})
        report = clustered_bootstrap(rows, left="egaa", right="always_refresh", iterations=200, seed=20261110)
        self.assertTrue(report["defined"])
        self.assertLess(report["observation_delta"]["upper"], 0)
        self.assertEqual(report["pairs"], 3)

    def test_local_update_keeps_done_nodes(self) -> None:
        done = PlanNode("read_notes", "read_fact", status="DONE")
        pending = PlanNode("write_note", "write_fact", args={"fact_key": "note.draft", "value_from": {"fact_key": "meeting.notes"}})
        updated = PlanNode(
            "write_note",
            "write_fact",
            args={"fact_key": "note.draft", "value_from": {"fact_key": "meeting.notes"}},
            status="PENDING",
        )
        result = local_or_full_update([done, pending], ["write_note"], {"prompt": "保持已完成的读取"}, {pending.id: updated})
        self.assertEqual(result.nodes[0].status, "DONE")
        self.assertNotEqual(result.mode, "stopped")
