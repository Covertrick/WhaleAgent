"""同一信念和计划上的策略契约。通知本身不把有效证据改成失效。"""

from __future__ import annotations

import unittest

from agent.algorithms.controller import decide
from agent.algorithms.evidence import apply_observation, goal_supported_by_belief
from agent.algorithms.planner import compile_plan, public_task_view
from agent.algorithms.types import BeliefState, ChangeNotice, DecideContext, Evidence, RiskRule
from evals.statebench.catalog import load_task


def _ready(policy: str, **kwargs) -> DecideContext:
    base = dict(
        policy=policy,
        goal_verified=False,
        now=2,
        risk=RiskRule("before_irreversible"),
        observe_budget=3,
        replan_budget=2,
    )
    base.update(kwargs)
    return DecideContext(**base)


def _nodes():
    nodes = compile_plan(public_task_view(load_task("s0_meeting_a"))).nodes
    nodes[0].status = "DONE"
    return nodes


def _belief() -> BeliefState:
    belief = BeliefState()
    apply_observation(belief, Evidence("ev:meeting.time", "meeting.time", "15:00", "task", "v1", 1, "VALID"))
    return belief


class PolicyContractTests(unittest.TestCase):
    def test_b1_notice_does_not_replan_valid_evidence(self) -> None:
        notice = ChangeNotice("notice:meeting.time", "meeting.time", 1)
        decision = decide(_belief(), _nodes(), _ready("B1", pending_notices=(notice,)))
        self.assertEqual(decision.kind, "CONTINUE")
        self.assertNotIn("ANY_NOTICE", decision.reason_codes)
        self.assertNotIn("OBSERVED_INVALIDATION", decision.reason_codes)

    def test_b2_observes_relevant_notice_and_b3_refreshes(self) -> None:
        notice = ChangeNotice("notice:meeting.time", "meeting.time", 1)
        risk = decide(_belief(), _nodes(), _ready("B2", pending_notices=(notice,)))
        refresh = decide(_belief(), _nodes(), _ready("B3", pending_notices=(notice,)))
        self.assertEqual(risk.reason_codes, ("FACT_CHANGED",))
        self.assertEqual(refresh.reason_codes, ("ALWAYS_REFRESH",))

    def test_b4_replans_a_notice_once(self) -> None:
        notice = ChangeNotice("notice:meeting.time", "meeting.time", 1)
        first = decide(_belief(), _nodes(), _ready("B4", pending_notices=(notice,)))
        second = decide(
            _belief(),
            _nodes(),
            _ready("B4", pending_notices=(notice,), replanned_notice_ids=frozenset({notice.notice_id})),
        )
        self.assertEqual(first.reason_codes, ("ANY_NOTICE",))
        self.assertEqual(second.reason_codes, ("FACT_CHANGED",))

    def test_hidden_truth_is_not_an_input(self) -> None:
        ctx = _ready("B2")
        left = decide(_belief(), _nodes(), ctx)
        right = decide(_belief(), _nodes(), ctx)
        self.assertEqual(left, right)

    def test_belief_goal_uses_receipts_only(self) -> None:
        belief = _belief()
        self.assertFalse(goal_supported_by_belief(belief, "meeting.time", "reminder.time", []))
        receipts = [{"tool": "write_fact", "fact_key": "reminder.time", "value": "15:00", "status": "CONFIRMED"}]
        self.assertTrue(goal_supported_by_belief(belief, "meeting.time", "reminder.time", receipts))

    def test_unverified_effect_recovers(self) -> None:
        decision = decide(_belief(), _nodes(), _ready("B2", unverified_node_ids=("write",)))
        self.assertEqual(decision.kind, "RECOVER")
        self.assertEqual(decision.reason_codes, ("UNVERIFIED",))
        self.assertEqual(decision.target_nodes, ("write",))


if __name__ == "__main__":
    unittest.main()
