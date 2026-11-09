"""局部修复保持已完成动作，单节点剩余时只重绑参数。"""

from __future__ import annotations

import unittest

from agent.algorithms.planner import compile_plan, public_task_view
from agent.algorithms.repair import repair_plan
from agent.algorithms.types import PlanNode
from evals.statebench.catalog import load_task


def _view() -> dict:
    return public_task_view(load_task("s0_meeting_a"))


def _plan() -> list[PlanNode]:
    return compile_plan(_view()).nodes


class RepairTests(unittest.TestCase):
    def test_done_node_stays_done(self) -> None:
        nodes = _plan()
        nodes[0].status = "DONE"
        result = repair_plan(nodes, ["read", "write"], _view(), "local")
        self.assertEqual(nodes[0].status, "DONE")
        self.assertEqual(result.repair_kind, "parameter_rebind")
        self.assertFalse(result.degraded)

    def test_single_pending_node_is_not_a_full_replan(self) -> None:
        nodes = _plan()
        nodes[0].status = "DONE"
        result = repair_plan(nodes, ["write"], _view(), "local")
        self.assertEqual(result.mode, "local")
        self.assertEqual(result.repair_kind, "parameter_rebind")
        self.assertEqual(result.nodes[1].id, "write")
        self.assertNotEqual(result.nodes[1].status, "DONE")

    def test_confirmed_write_is_not_reissued(self) -> None:
        nodes = _plan()
        nodes[0].status = "DONE"
        result = repair_plan(nodes, ["read", "write"], _view(), "full", confirmed_writes=("reminder.time",))
        write = next(node for node in result.nodes if node.id == "write")
        self.assertEqual(write.status, "DONE")
        self.assertEqual(result.nodes[0].status, "DONE")

    def test_unverified_effect_stops_without_a_new_write(self) -> None:
        nodes = _plan()
        before = [node.id for node in nodes]
        result = repair_plan(nodes, ["write"], _view(), "full", unverified_effects=("write",))
        self.assertEqual(result.mode, "stopped")
        self.assertEqual(result.repair_kind, "stopped")
        self.assertEqual([node.id for node in result.nodes], before)
        self.assertTrue(all(node.status != "DONE" or node.id == "read" for node in result.nodes))

    def test_illegal_local_edit_degrades(self) -> None:
        nodes = _plan()
        broken = PlanNode("write", "write_fact", depends_on_nodes=["write"])
        result = repair_plan(nodes, ["write"], _view(), "local", replacements={"write": broken})
        self.assertTrue(result.degraded)
        self.assertEqual(result.repair_kind, "full_replan")

    def test_other_branch_stays_when_one_fact_changes(self) -> None:
        nodes = [
            PlanNode("read_time", "read_fact", args={"fact_key": "meeting.time"}),
            PlanNode(
                "write_time",
                "write_fact",
                args={"fact_key": "reminder.time", "value_from": {"fact_key": "meeting.time"}},
                depends_on_nodes=["read_time"],
                requires_evidence=["ev:meeting.time"],
                irreversible=True,
            ),
            PlanNode("read_note", "read_fact", args={"fact_key": "note.status"}),
            PlanNode(
                "write_note",
                "write_fact",
                args={"fact_key": "note.backup_status", "value_from": {"fact_key": "note.status"}},
                depends_on_nodes=["read_note"],
                requires_evidence=["ev:note.status"],
                irreversible=True,
            ),
        ]
        replacement = PlanNode(
            "write_time",
            "write_fact",
            args={"fact_key": "reminder.time", "value_from": {"fact_key": "meeting.time"}},
            depends_on_nodes=["read_time"],
            requires_evidence=["ev:meeting.time"],
            irreversible=True,
        )
        result = repair_plan(nodes, ["write_time"], {}, "local", replacements={"write_time": replacement})
        self.assertEqual(result.repair_kind, "local_structural_repair")
        self.assertIs(result.nodes[2], nodes[2])
        self.assertIs(result.nodes[3], nodes[3])
        self.assertEqual(result.nodes[3].args["fact_key"], "note.backup_status")


if __name__ == "__main__":
    unittest.main()
