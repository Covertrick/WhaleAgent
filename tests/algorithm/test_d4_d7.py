"""D4–D7 确定性语义。不调用模型，也不连接 QQ。"""

from __future__ import annotations

import unittest
from pathlib import Path

from agent.algorithms.controller import (
    acknowledgement_allowed,
    acknowledge,
    decide,
)
from agent.algorithms.evidence import apply_observation, current_evidence, goal_met_by_belief
from agent.algorithms.invalidation import affected_ids, change_relation, dependent_subgraph
from agent.algorithms.planner import (
    PlanError,
    ResolveError,
    compile_plan,
    plan_errors,
    public_task_view,
    resolve_args,
)
from agent.algorithms.types import BeliefState, ChangeNotice, DecideContext, Evidence, PlanNode, RiskRule
from agent.algorithms.validator import precondition
from evals.statebench.catalog import load_splits, load_task
from evals.statebench.environment import Environment, HiddenEvent
from tests.algorithm.oracle import compile_oracle_fixture


def _ctx(policy: str = "B2", **kwargs) -> DecideContext:
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


def _view(task_id: str = "s1_meeting_a") -> dict:
    return public_task_view(load_task(task_id))


def _observe(belief: BeliefState, fact: str, value: str, version: str, observed_at: int, status: str = "VALID"):
    return apply_observation(
        belief,
        Evidence(f"ev:{fact}", fact, value, "task", version, observed_at, status),
    )


class D4D7Tests(unittest.TestCase):
    def test_t01_dev_tasks_compile(self) -> None:
        for task_id in load_splits()["dev"]:
            plan = compile_plan(_view(task_id))
            self.assertEqual(plan.plan_origin, "structured_task_compilation")
            self.assertEqual([node.id for node in plan.nodes], ["read", "write"])
            self.assertEqual(plan.nodes[1].depends_on_nodes, ["read"])
            source = _view(task_id)["source_key"]
            self.assertEqual(plan.nodes[1].requires_evidence, [f"ev:{source}"])
            self.assertTrue(plan.nodes[1].irreversible)
            self.assertFalse(plan.nodes[0].irreversible)
            self.assertTrue(plan_errors(plan.nodes).valid)
            self.assertNotIn("value", plan.nodes[1].args)

    def test_t02_missing_fields_and_unknown_structure(self) -> None:
        view = _view()
        view.pop("source_key")
        with self.assertRaises(PlanError):
            compile_plan(view)
        view = _view()
        view["dependency_structure"] = "parallel"
        with self.assertRaises(PlanError):
            compile_plan(view)

    def test_t03_hidden_keys_are_rejected(self) -> None:
        view = _view()
        view["readable"] = ["meeting.room"]
        with self.assertRaises(PlanError):
            compile_plan(view)
        view = _view()
        view["writable"] = ["meeting.room"]
        with self.assertRaises(PlanError):
            compile_plan(view)

    def test_t04_graph_errors_keep_their_codes(self) -> None:
        duplicate = plan_errors(
            [PlanNode("read", "read_fact"), PlanNode("read", "write_fact")]
        )
        self.assertEqual(duplicate.error_code, "PLAN_INVALID")
        self.assertIn("duplicate_id:read", duplicate.details)
        self_loop = plan_errors([PlanNode("read", "read_fact", depends_on_nodes=["read"])])
        self.assertEqual(self_loop.error_code, "PLAN_INVALID")
        dangling = plan_errors([PlanNode("write", "write_fact", depends_on_nodes=["read"])])
        self.assertEqual(dangling.error_code, "PLAN_INVALID")
        unsupported = plan_errors([PlanNode("x", "drop_table")])
        self.assertEqual(unsupported.error_code, "PLAN_INVALID")
        cycle = plan_errors(
            [
                PlanNode("a", "read_fact", depends_on_nodes=["b"]),
                PlanNode("b", "write_fact", depends_on_nodes=["a"]),
            ]
        )
        self.assertEqual(cycle.error_code, "PLAN_CYCLE")
        decision = decide(BeliefState(), [PlanNode("write", "write_fact", depends_on_nodes=["read"])], _ctx())
        self.assertEqual(decision.reason_codes, ("PLAN_INVALID",))

    def test_t05_write_without_evidence_observes(self) -> None:
        plan = compile_plan(_view("s0_meeting_a"))
        plan.nodes[0].status = "DONE"
        self.assertEqual(precondition(plan.nodes[1], BeliefState()), "UNKNOWN")
        decision = decide(BeliefState(), plan.nodes, _ctx())
        self.assertEqual(decision.kind, "OBSERVE")
        self.assertIn("MISSING_EVIDENCE", decision.reason_codes)
        self.assertEqual(decision.observation_keys, ("meeting.time",))

    def test_t06_invalid_beats_unknown(self) -> None:
        belief = BeliefState()
        belief.evidence["bad"] = Evidence("bad", "meeting.time", "15:00", "task", "v1", 1, "INVALID")
        belief.evidence["later"] = Evidence("later", "meeting.room", "Room-A", "task", "v1", 1, "UNKNOWN")
        node = PlanNode("write", "write_fact", requires_evidence=["later", "bad"])
        self.assertEqual(precondition(node, belief), "INVALID")
        belief.evidence["bad"].status = "SUPERSEDED"
        self.assertEqual(precondition(node, belief), "UNKNOWN")
        belief.evidence["later"].status = "VALID"
        belief.evidence["bad"].status = "VALID"
        self.assertEqual(precondition(node, belief), "VALID")

    def test_t07_three_versions_keep_history(self) -> None:
        belief = BeliefState()
        first = _observe(belief, "meeting.time", "15:00", "v1", 1)
        second = _observe(belief, "meeting.time", "16:00", "v2", 2)
        third = _observe(belief, "meeting.time", "17:00", "v3", 3)
        current = current_evidence(belief, "meeting.time")
        self.assertIsNotNone(current)
        self.assertEqual(current.source_version, "v3")
        self.assertEqual(current.value, "17:00")
        self.assertEqual(belief.evidence[first.observation_id].status, "SUPERSEDED")
        self.assertEqual(belief.evidence[first.observation_id].source_version, "v1")
        self.assertEqual(belief.evidence[second.observation_id].status, "SUPERSEDED")
        self.assertEqual(belief.evidence[second.observation_id].value, "16:00")
        self.assertEqual(belief.evidence[third.observation_id].status, "VALID")
        self.assertEqual(len(set(belief.observation_history)), 3)
        self.assertFalse(goal_met_by_belief((("meeting.time", "15:00"),), belief))
        self.assertTrue(goal_met_by_belief((("meeting.time", "17:00"),), belief))

    def test_t08_same_timestamp_does_not_reuse_history_id(self) -> None:
        belief = BeliefState()
        first = _observe(belief, "meeting.time", "15:00", "v1", 4)
        second = _observe(belief, "meeting.time", "15:00", "v1", 4)
        self.assertNotEqual(first.observation_id, second.observation_id)
        self.assertIn(first.observation_id, belief.evidence)
        self.assertIn(second.observation_id, belief.evidence)
        self.assertEqual(current_evidence(belief, "meeting.time").source_version, "v1")

    def test_t09_older_version_does_not_replace_current(self) -> None:
        belief = BeliefState()
        _observe(belief, "meeting.time", "16:00", "v2", 5)
        older = _observe(belief, "meeting.time", "15:00", "v1", 3)
        self.assertEqual(older.effect, "archived")
        self.assertEqual(current_evidence(belief, "meeting.time").source_version, "v2")
        self.assertEqual(belief.evidence[older.observation_id].status, "SUPERSEDED")
        other = BeliefState()
        _observe(other, "meeting.time", "16:00", "rev-b", 5)
        late = _observe(other, "meeting.time", "15:00", "rev-a", 9)
        self.assertEqual(late.effect, "archived")
        self.assertEqual(current_evidence(other, "meeting.time").source_version, "rev-b")

    def test_t10_old_observation_does_not_revive_invalid_current(self) -> None:
        belief = BeliefState()
        current = _observe(belief, "meeting.time", "16:00", "v2", 6)
        from agent.algorithms.evidence import mark_status

        mark_status(belief, [current.current.id], "INVALID")
        late = _observe(belief, "meeting.time", "15:00", "v1", 1)
        self.assertEqual(late.effect, "archived")
        slot = belief.evidence[belief.slots["meeting.time"]]
        self.assertEqual(slot.source_version, "v2")
        self.assertEqual(slot.status, "INVALID")
        self.assertNotEqual(belief.evidence[late.observation_id].status, "VALID")
        self.assertIsNone(current_evidence(belief, "meeting.time"))

    def test_t11_same_version_conflict_is_explicit(self) -> None:
        belief = BeliefState()
        _observe(belief, "meeting.time", "15:00", "v1", 1)
        conflict = _observe(belief, "meeting.time", "16:00", "v1", 2)
        self.assertEqual(conflict.effect, "conflict")
        self.assertEqual(current_evidence(belief, "meeting.time").value, "15:00")
        self.assertEqual(belief.evidence[conflict.observation_id].status, "UNKNOWN")

    def test_t12_other_fact_does_not_change_current(self) -> None:
        belief = BeliefState()
        _observe(belief, "meeting.time", "15:00", "v1", 1)
        _observe(belief, "meeting.room", "Room-B", "v2", 2)
        self.assertEqual(current_evidence(belief, "meeting.time").value, "15:00")
        self.assertEqual(current_evidence(belief, "meeting.time").source_version, "v1")

    def test_t13_relevant_notice_observes_without_invalidating(self) -> None:
        plan = compile_plan(_view("s0_meeting_a"))
        belief = BeliefState()
        _observe(belief, "meeting.time", "15:00", "v1", 1)
        plan.nodes[0].status = "DONE"
        notice = ChangeNotice("n-time", "meeting.time", 2)
        decision = decide(belief, plan.nodes, _ctx(pending_notices=(notice,)))
        self.assertEqual(decision.kind, "OBSERVE")
        self.assertEqual(decision.reason_codes, ("FACT_CHANGED",))
        self.assertEqual(decision.observation_keys, ("meeting.time",))
        self.assertIn("write", decision.target_nodes)
        self.assertEqual(current_evidence(belief, "meeting.time").status, "VALID")

    def test_t14_unrelated_notice_does_not_invalidate(self) -> None:
        plan = compile_plan(_view("s0_meeting_a"))
        belief = BeliefState()
        _observe(belief, "meeting.time", "15:00", "v1", 1)
        before = current_evidence(belief, "meeting.time").status
        decision = decide(belief, plan.nodes, _ctx(visible_changes=("meeting.room",)))
        self.assertEqual(change_relation({"meeting.time"}, "meeting.room"), "unrelated")
        self.assertEqual(affected_ids(plan.nodes, belief, ["meeting.room"]), [])
        self.assertNotIn("OBSERVED_INVALIDATION", decision.reason_codes)
        self.assertNotIn("FACT_CHANGED", decision.reason_codes)
        self.assertEqual(current_evidence(belief, "meeting.time").status, before)

    def test_t15_parent_key_is_unknown_scope(self) -> None:
        plan = compile_plan(_view("s0_meeting_a"))
        belief = BeliefState()
        _observe(belief, "meeting.time", "15:00", "v1", 1)
        plan.nodes[0].status = "DONE"
        notice = ChangeNotice("n-parent", "meeting", 2)
        decision = decide(belief, plan.nodes, _ctx(pending_notices=(notice,)))
        self.assertEqual(decision.reason_codes, ("UNKNOWN_SCOPE",))
        self.assertEqual(decision.observation_keys, ("meeting.time",))
        self.assertIn("write", decision.target_nodes)
        self.assertEqual(affected_ids(plan.nodes, belief, ["meeting"]), [])
        self.assertEqual(current_evidence(belief, "meeting.time").status, "VALID")

    def test_t16_hidden_event_is_not_a_notice(self) -> None:
        env = Environment(
            {"meeting.time": {"value": "15:00", "version": "v1"}},
            [HiddenEvent("before_write", "meeting.time", "16:00", "v2", notify=False)],
        )
        try:
            belief = BeliefState()
            _observe(belief, "meeting.time", "15:00", "v1", 1)
            self.assertEqual(env.apply_checkpoint("before_write"), [])
            plan = compile_plan(_view("s0_meeting_a"))
            decision = decide(belief, plan.nodes, _ctx(visible_changes=()))
            self.assertNotIn("FACT_CHANGED", decision.reason_codes)
            self.assertEqual(current_evidence(belief, "meeting.time").value, "15:00")
            self.assertEqual(env.truth["meeting.time"]["value"], "16:00")
        finally:
            env.close()

    def test_t17_acknowledged_notice_does_not_repeat(self) -> None:
        plan = compile_plan(_view("s0_meeting_a"))
        belief = BeliefState()
        _observe(belief, "meeting.time", "15:00", "v1", 1)
        plan.nodes[0].status = "DONE"
        notice = ChangeNotice("n-time", "meeting.time", 2)
        ctx = _ctx(pending_notices=(notice,))
        first = decide(belief, plan.nodes, ctx)
        self.assertEqual(first.reason_codes, ("FACT_CHANGED",))
        updated = _observe(belief, "meeting.time", "16:00", "v2", 3)
        self.assertTrue(acknowledgement_allowed(updated, notice))
        ctx = acknowledge(ctx, notice.notice_id)
        second = decide(belief, plan.nodes, ctx)
        self.assertNotIn("FACT_CHANGED", second.reason_codes)
        self.assertEqual(second.kind, "CONTINUE")

    def test_t18_failed_observation_keeps_the_notice(self) -> None:
        plan = compile_plan(_view("s0_meeting_a"))
        belief = BeliefState()
        _observe(belief, "meeting.time", "16:00", "v2", 3)
        plan.nodes[0].status = "DONE"
        notice = ChangeNotice("n-time", "meeting.time", 4)
        ctx = _ctx(pending_notices=(notice,))
        self.assertEqual(decide(belief, plan.nodes, ctx).reason_codes, ("FACT_CHANGED",))
        late = _observe(belief, "meeting.time", "15:00", "v1", 1)
        self.assertFalse(acknowledgement_allowed(late, notice))
        self.assertEqual(decide(belief, plan.nodes, ctx).reason_codes, ("FACT_CHANGED",))

    def test_t19_done_node_does_not_stop_propagation(self) -> None:
        nodes = [
            PlanNode("a", "read_fact", args={"fact_key": "meeting.time"}, requires_evidence=["ev:meeting.time"], status="DONE"),
            PlanNode("b", "read_fact", args={"fact_key": "meeting.time"}, depends_on_nodes=["a"], status="DONE"),
            PlanNode(
                "c",
                "write_fact",
                args={"fact_key": "reminder.time", "value_from": {"fact_key": "meeting.time"}},
                depends_on_nodes=["b"],
                requires_evidence=["ev:meeting.time"],
            ),
        ]
        belief = BeliefState()
        _observe(belief, "meeting.time", "15:00", "v1", 1)
        affected = affected_ids(nodes, belief, ["meeting.time"])
        reachable = set(dependent_subgraph(nodes, ["a"]))
        done = {"a", "b"}
        self.assertIn("c", affected)
        self.assertNotIn("b", affected)
        self.assertNotIn("a", affected)
        self.assertTrue(set(affected) <= reachable - done)

    def test_t20_finished_plan_is_not_goal_met(self) -> None:
        plan = compile_plan(_view("s0_meeting_a"))
        for node in plan.nodes:
            node.status = "DONE"
        decision = decide(BeliefState(), plan.nodes, _ctx(goal_verified=False))
        self.assertEqual(decision.reason_codes, ("GOAL_UNVERIFIED",))
        verified = decide(BeliefState(), plan.nodes, _ctx(goal_verified=True))
        self.assertEqual(verified.reason_codes, ("GOAL_MET",))

    def test_t21_compilation_is_stable(self) -> None:
        left = compile_plan(_view())
        right = compile_plan(_view())
        self.assertEqual(left.serialize(), right.serialize())

    def test_t22_private_fields_do_not_enter_the_plan(self) -> None:
        raw = load_task("s1_meeting_a")
        raw["environment_event"] = {"value": "16:00"}
        with self.assertRaises(PlanError):
            compile_plan(raw)
        plan = compile_plan(public_task_view(load_task("s1_meeting_a")))
        self.assertNotIn("16:00", plan.serialize())
        self.assertNotIn("environment_event", plan.serialize())
        oracle = compile_oracle_fixture(load_task("s1_meeting_a"))
        self.assertEqual(oracle.plan_origin, "oracle_fixture")
        self.assertNotIn("16:00", oracle.serialize())
        root = Path(__file__).resolve().parents[2]
        for relative in (
            "agent/algorithms/controller.py",
            "evals/statebench/b0.py",
            "evals/statebench/runner.py",
        ):
            self.assertNotIn("compile_oracle_fixture", (root / relative).read_text(encoding="utf-8"))

    def test_delayed_binding_refuses_stale_evidence(self) -> None:
        plan = compile_plan(_view("s0_meeting_a"))
        belief = BeliefState()
        _observe(belief, "meeting.time", "15:00", "v1", 1)
        self.assertEqual(resolve_args(plan.nodes[1], belief)["value"], "15:00")
        self.assertNotIn("value", plan.nodes[1].args)
        from agent.algorithms.evidence import mark_status

        mark_status(belief, [belief.slots["meeting.time"]], "SUPERSEDED")
        with self.assertRaises(ResolveError):
            resolve_args(plan.nodes[1], belief)

    def test_relevant_notice_blocks_unverified_goal(self) -> None:
        plan = compile_plan(_view("s0_meeting_a"))
        belief = BeliefState()
        _observe(belief, "meeting.time", "15:00", "v1", 1)
        notice = ChangeNotice("n-time", "meeting.time", 2)
        decision = decide(belief, plan.nodes, _ctx(goal_verified=True, pending_notices=(notice,)))
        self.assertEqual(decision.reason_codes, ("FACT_CHANGED",))


if __name__ == "__main__":
    unittest.main()
