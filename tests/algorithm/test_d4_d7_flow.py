"""编译、观察、通知、再观察。不调用模型，也不执行真实写入。"""

from __future__ import annotations

import unittest

from agent.algorithms.controller import acknowledgement_allowed, acknowledge, decide
from agent.algorithms.evidence import apply_observation, current_evidence
from agent.algorithms.planner import compile_plan, public_task_view, resolve_args
from agent.algorithms.types import BeliefState, ChangeNotice, DecideContext, Evidence, RiskRule
from agent.algorithms.validator import precondition
from evals.statebench.catalog import load_task


def _ctx(**kwargs) -> DecideContext:
    base = dict(
        policy="B2",
        goal_verified=False,
        now=5,
        risk=RiskRule("evidence_age", 100),
        observe_budget=3,
        replan_budget=2,
    )
    base.update(kwargs)
    return DecideContext(**base)


class FlowTests(unittest.TestCase):
    def test_compile_observe_notice_and_reobserve(self) -> None:
        plan = compile_plan(public_task_view(load_task("s0_meeting_a")))
        belief = BeliefState()
        self.assertEqual(precondition(plan.nodes[1], belief), "UNKNOWN")
        first = decide(belief, plan.nodes, _ctx())
        self.assertEqual(first.kind, "CONTINUE")
        self.assertEqual(first.target_nodes, ("read",))

        initial = apply_observation(
            belief,
            Evidence("ev:meeting.time", "meeting.time", "15:00", "task", "v1", 1, "VALID"),
        )
        self.assertEqual(initial.effect, "accepted")
        self.assertEqual(current_evidence(belief, "meeting.time").value, "15:00")
        plan.nodes[0].status = "DONE"

        notice = ChangeNotice("n-time", "meeting.time", 2)
        noticed = decide(belief, plan.nodes, _ctx(pending_notices=(notice,)))
        self.assertEqual(noticed.reason_codes, ("FACT_CHANGED",))
        self.assertEqual(noticed.observation_keys, ("meeting.time",))
        self.assertEqual(noticed.target_nodes, ("write",))
        self.assertEqual(current_evidence(belief, "meeting.time").status, "VALID")
        self.assertEqual(current_evidence(belief, "meeting.time").source_version, "v1")

        revised = apply_observation(
            belief,
            Evidence("ev:meeting.time", "meeting.time", "16:00", "task", "v2", 3, "VALID"),
        )
        self.assertEqual(revised.effect, "replaced")
        self.assertEqual(belief.evidence[initial.observation_id].status, "SUPERSEDED")
        self.assertEqual(belief.evidence[initial.observation_id].value, "15:00")
        self.assertEqual(current_evidence(belief, "meeting.time").value, "16:00")
        self.assertTrue(acknowledgement_allowed(revised, notice))
        ctx = acknowledge(_ctx(pending_notices=(notice,)), notice.notice_id)
        continued = decide(belief, plan.nodes, ctx)
        self.assertEqual(continued.kind, "CONTINUE")
        self.assertEqual(continued.target_nodes, ("write",))
        self.assertNotIn("FACT_CHANGED", continued.reason_codes)
        self.assertEqual(resolve_args(plan.nodes[1], belief)["value"], "16:00")
        self.assertEqual(plan.nodes[1].args["value_from"], {"fact_key": "meeting.time"})


if __name__ == "__main__":
    unittest.main()
