"""EGAA 不变量。不调用模型，也不连接 QQ。"""

from __future__ import annotations

import unittest
from pathlib import Path

from agent.algorithms.controller import decide
from agent.algorithms.evidence import apply_observation, goal_met_by_belief, mark_status
from agent.algorithms.invalidation import affected_ids
from agent.algorithms.repair import apply_replan_marks
from agent.algorithms.types import BeliefState, DecideContext, Evidence, PlanNode, RiskRule
from evals.statebench.environment import Environment, HiddenEvent
from evals.statebench.scorer import false_invalidations, goal_met


def _evidence(status: str = "VALID", *, age_at: int = 0, fact: str = "meeting.time", value: str = "15:00") -> Evidence:
    return Evidence(
        "ev-time",
        fact,
        value,
        "doc",
        "v1",
        age_at,
        status,
    )


def _nodes() -> list[PlanNode]:
    return [
        PlanNode("read", "read_meeting", requires_evidence=["ev-time"]),
        PlanNode(
            "remind",
            "create_reminder",
            depends_on_nodes=["read"],
            requires_evidence=["ev-time"],
            irreversible=True,
        ),
    ]


def _ctx(policy: str, **kwargs) -> DecideContext:
    base = dict(
        policy=policy,
        goal_verified=False,
        now=5,
        risk=RiskRule("evidence_age", 100),
        observe_budget=3,
        replan_budget=2,
    )
    base.update(kwargs)
    return DecideContext(**base)


class InvariantTests(unittest.TestCase):
    def test_algorithms_do_not_import_channel(self) -> None:
        """静态 AST 扫描 agent/algorithms，包含函数内部的 import。

        importlib 和 __import__ 不在这项承诺内。
        """
        from evals.statebench.imports_scan import scan_static_channel_imports

        root = Path(__file__).resolve().parents[2] / "agent" / "algorithms"
        self.assertEqual(scan_static_channel_imports(root), [])

    def test_missing_evidence_observes(self) -> None:
        decision = decide(BeliefState(), _nodes(), _ctx("B2"))
        self.assertEqual(decision.kind, "OBSERVE")
        self.assertIn("MISSING_EVIDENCE", decision.reason_codes)

    def test_hidden_change_does_not_update_belief(self) -> None:
        env = Environment(
            {"meeting.time": {"value": "15:00", "version": "v1"}},
            [HiddenEvent("before_write", "meeting.time", "16:00", "v2", notify=False)],
        )
        belief = BeliefState()
        apply_observation(belief, _evidence())
        notices = env.apply_checkpoint("before_write")
        self.assertEqual(notices, [])
        self.assertEqual(belief.evidence["ev-time"].value, "15:00")
        self.assertEqual(belief.evidence["ev-time"].status, "VALID")
        decision = decide(belief, _nodes(), _ctx("B2", visible_changes=tuple(notices)))
        self.assertNotIn("OBSERVED_INVALIDATION", decision.reason_codes)
        self.assertEqual(env.truth["meeting.time"]["value"], "16:00")

    def test_known_invalidation_blocks_dependents(self) -> None:
        belief = BeliefState()
        apply_observation(belief, _evidence())
        mark_status(belief, ["ev-time"], "INVALID")
        nodes = _nodes()
        nodes[0].status = "DONE"
        decision = decide(belief, nodes, _ctx("B2"))
        self.assertEqual(decision.kind, "REPLAN")
        self.assertIn("remind", decision.target_nodes)
        self.assertNotIn("read", decision.target_nodes)

    def test_unrelated_fact_does_not_spread(self) -> None:
        belief = BeliefState()
        apply_observation(belief, _evidence())
        self.assertEqual(affected_ids(_nodes(), belief, ["meeting.room"]), [])
        decision = decide(belief, _nodes(), _ctx("B2", visible_changes=("meeting.room",)))
        self.assertEqual(decision.kind, "CONTINUE")

    def test_done_node_is_not_reopened(self) -> None:
        nodes = _nodes()
        nodes[0].status = "DONE"
        changed = apply_replan_marks(nodes, ["read", "remind"])
        self.assertEqual(changed, ["remind"])
        self.assertEqual(nodes[0].status, "DONE")
        self.assertEqual(nodes[1].status, "BLOCKED")

    def test_observe_budget_stops(self) -> None:
        decision = decide(BeliefState(), _nodes(), _ctx("B2", observes_used=3))
        self.assertEqual(decision.kind, "STOP")
        self.assertIn("OBSERVE_BUDGET", decision.reason_codes)

    def test_claim_text_is_not_success(self) -> None:
        env = Environment({"reminder.time": {"value": "15:00", "version": "v1"}})
        self.assertFalse(goal_met({"reminder.time": "16:00"}, env))
        belief = BeliefState()
        apply_observation(belief, _evidence(value="16:00"))
        self.assertTrue(goal_met_by_belief((("meeting.time", "16:00"),), belief))
        self.assertFalse(goal_met({"meeting.time": "16:00"}, env))

    def test_reset_restores_snapshot(self) -> None:
        env = Environment(
            {"meeting.time": {"value": "15:00", "version": "v1"}},
            [HiddenEvent("before_write", "meeting.time", "16:00", "v2", False)],
        )
        token = env.snapshot_token()
        env.apply_checkpoint("before_write")
        env.reset()
        self.assertEqual(env.snapshot_token(), token)

    def test_false_invalidation_counts_matching_version(self) -> None:
        env = Environment({"meeting.time": {"value": "15:00", "version": "v1"}})
        self.assertEqual(false_invalidations([("meeting.time", "v1")], env), 1)
        self.assertEqual(false_invalidations([("meeting.time", "v0")], env), 0)

    def test_b4_replans_on_any_notice(self) -> None:
        belief = BeliefState()
        apply_observation(belief, _evidence())
        decision = decide(belief, _nodes(), _ctx("B4", visible_changes=("meeting.room",)))
        self.assertEqual(decision.kind, "REPLAN")
        self.assertIn("ANY_NOTICE", decision.reason_codes)

    def test_b3_refreshes_before_continue(self) -> None:
        belief = BeliefState()
        apply_observation(belief, _evidence())
        decision = decide(belief, _nodes(), _ctx("B3"))
        self.assertEqual(decision.reason_codes, ("ALWAYS_REFRESH",))

    def test_single_age_threshold(self) -> None:
        belief = BeliefState()
        apply_observation(belief, _evidence(age_at=0))
        fresh = decide(belief, _nodes(), _ctx("B2", now=5, risk=RiskRule("evidence_age", 10)))
        stale = decide(belief, _nodes(), _ctx("B2", now=5, risk=RiskRule("evidence_age", 5)))
        self.assertEqual(fresh.kind, "CONTINUE")
        self.assertIn("POTENTIALLY_STALE", stale.reason_codes)
        self.assertEqual(stale.threshold, "max_age=5")


if __name__ == "__main__":
    unittest.main()
