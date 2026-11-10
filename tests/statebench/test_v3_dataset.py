"""v3 数据集只做离线审计，不调用模型。"""

from __future__ import annotations

import json
import unittest

from agent.algorithms.types import PlanNode
from agent.policies.planning import local_or_full_update
from evals.statebench.v3.audit import audit_rows
from evals.statebench.v3.catalog import DEV_IDS, SPECS, all_tasks
from evals.statebench.v3.statistics import clustered_bootstrap
from evals.statebench.v3.world import play, score


class V3DatasetTests(unittest.TestCase):
    def test_forty_eight_blueprints_and_developer_review(self) -> None:
        rows = audit_rows()
        self.assertEqual(len(SPECS), 48)
        self.assertEqual(len(all_tasks()), 96)
        self.assertEqual(len(rows), 96)
        self.assertEqual({spec.split for spec in SPECS}, {"dev", "val", "test"})
        self.assertEqual({spec.blueprint_id for spec in SPECS if spec.split == "dev"}, set(DEV_IDS))
        self.assertTrue(all(row["human_review"] == "developer_reviewed" for row in rows))
        self.assertTrue(all(row["third_party"] == "no" for row in rows))
        self.assertTrue(all(row["reviewer"] == "developer" for row in rows))
        self.assertTrue(all(row["review_note"] for row in rows))
        self.assertTrue(all(row["notes"] == "" for row in rows))
        fingerprints = {}
        for task in all_tasks():
            payload = json.dumps(
                {
                    "sources": [(item["v1"], item["v2"]) for item in task["sources"]],
                    "writes": task["writes"],
                    "notify": task["notify"],
                    "change_on": task["change_on"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            fingerprints.setdefault(payload, set()).add(task["blueprint_id"])
        collided = [ids for ids in fingerprints.values() if len(ids) > 1]
        self.assertEqual(collided, [])
        shapes = {spec.scenario: {item.dag_shape for item in SPECS if item.scenario == spec.scenario} for spec in SPECS}
        for scenario, found in shapes.items():
            self.assertEqual(found, {"parallel", "fanout", "chain", "join"}, scenario)

    def test_bool_plan_fields_do_not_crash_parser(self) -> None:
        from agent.algorithms.planner import PlanError
        from agent.policies.planning import _nodes_from_text

        text = (
            '{"nodes":[{"id":"a","action":"read_fact","args":{"fact_key":"会议纪要"},'
            '"depends_on_nodes":true,"requires_evidence":false,"irreversible":false}]}'
        )
        try:
            nodes = _nodes_from_text(text)
        except PlanError:
            return
        self.assertEqual(nodes[0].depends_on_nodes, [])

    def test_live_hint_does_not_carry_hidden_tokens(self) -> None:
        from evals.statebench.v3.live import _goal_pairs, _project, schema_hint

        task = next(item for item in all_tasks() if item["task_id"] == "s1_join_notified_v1")
        hint = schema_hint(task)
        secret = next(item["token_v2"] for item in task["sources"] if item["token_v2"] != item["token_v1"])
        self.assertNotIn(secret, hint)
        self.assertNotIn(secret, task["public_goal"])
        self.assertEqual(_goal_pairs(task), (("未完成", "未声明目标"),))
        text = "待办：接听告警。负责人：新值班。时间：2026-11-20T08:00:00+08:00。补充 2026-11-22T08:00:00+08:00"
        self.assertEqual(_project(text, "draft:1#todo"), "待办：接听告警")
        self.assertEqual(_project(text, "draft:1#owner"), "负责人：新值班")
        self.assertEqual(_project(text, "schedule.reminder"), "2026-11-22T08:00:00+08:00")
        from agent.policies.planning import _nodes_from_text

        parsed = _nodes_from_text(
            '{"nodes":[{"id":"w","action":"write_fact","args":{"fact_key":"draft:1","value_from":"会议纪要"},'
            '"depends_on_nodes":["r"],"requires_evidence":[],"irreversible":false},'
            '{"id":"r","action":"read_fact","args":{"fact_key":"会议纪要"}}]}'
        )
        self.assertEqual(parsed[0].args["value_from"], {"fact_key": "会议纪要"})

    def test_irrelevant_old_token_fails_and_review_is_not_third_party(self) -> None:
        task = next(item for item in all_tasks() if item["task_id"] == "s2_parallel_irrelevant_v1")
        world = play(task, "correct")
        self.assertTrue(score(task, world)["success"])
        slot = next(item["slot"] for item in task["writes"] if item["kind"] == "draft")
        old = next(item["token_v1"] for item in task["sources"] if item["sid"] == "extra")
        world.drafts[slot] = world.drafts[slot] + old
        self.assertFalse(score(task, world)["success"])
        self.assertNotIn("第三方通过", "".join(row["review_note"] for row in audit_rows()))

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
