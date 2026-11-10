"""EGAA 策略。调用 algorithms.decide，不执行工具，不写账本。"""

from __future__ import annotations

from typing import Callable

from agent.algorithms.controller import acknowledgement_allowed, decide
from agent.algorithms.evidence import apply_observation, current_evidence, mark_status
from agent.algorithms.planner import ResolveError, resolve_args
from agent.algorithms.repair import repair_plan
from agent.algorithms.types import BeliefState, ChangeNotice, DecideContext, PlanNode, RiskRule
from agent.application.catalog import read_call, write_call
from agent.application.effects import effect_status
from agent.application.evidence_codec import evidence_from_tool
from agent.application.revisions import ContentRevisionLedger
from agent.application.goal_verifier import goal_report
from agent.engine.events import StepDecision, ToolCall
from agent.engine.runner import StepPolicy

REFRESH_REASONS = {"ALWAYS_REFRESH", "POTENTIALLY_STALE", "FACT_CHANGED", "UNKNOWN_SCOPE", "MISSING_EVIDENCE"}


class EGAAPolicy(StepPolicy):
    def __init__(
        self,
        nodes: list[PlanNode],
        *,
        policy: str = "B2",
        goal_pairs: tuple[tuple[str, str], ...] = (),
        visible_facts: dict | None = None,
        before_decision: Callable[[int, list[PlanNode]], list[ChangeNotice]] | None = None,
        risk: RiskRule | None = None,
        observe_budget: int = 6,
        replan_budget: int = 2,
        read_binding: Callable[[str], tuple[str, dict]] = read_call,
        write_binding: Callable[[str, str], tuple[str, dict]] = write_call,
        grounder: Callable[..., object] | None = None,
        revision_probe: Callable[[str], str] | None = None,
        commit_window_changed: Callable[[str], bool] | None = None,
        replan_fn: Callable[[], list[PlanNode]] | None = None,
    ) -> None:
        self.nodes = nodes
        self.policy_name = "egaa"
        self.policy_version = "2"
        self.evidence_policy = policy
        self.goal_pairs = goal_pairs
        self.visible_facts = visible_facts or {}
        self.before_decision = before_decision
        self.risk = risk or RiskRule("before_irreversible")
        self.observe_budget = observe_budget
        self.replan_budget = replan_budget
        self.read_binding = read_binding
        self.write_binding = write_binding
        self.grounder = grounder
        self.revision_probe = revision_probe
        self.commit_window_changed = commit_window_changed
        self.replan_fn = replan_fn
        self.revisions = ContentRevisionLedger()
        self.pool_handlers: dict = {}
        self.belief = BeliefState()
        self.notices: list[ChangeNotice] = []
        self.acknowledged: set[str] = set()
        self.replanned: set[str] = set()
        self.refreshed: set[str] = set()
        self.unverified: list[str] = []
        self.receipts: list[dict] = []
        self.confirmed_writes: set[str] = set()
        self.decisions: list[dict] = []
        self.observes_used = 0
        self.replans_used = 0
        self.now = 0
        self.termination = ""
        self.last_text = ""
        self._pending: dict[str, dict] = {}
        self._recover_listed = False
        self._stop_answer = ""
        self._settled_unknown: set[str] = set()
        self._closed_writes: set[str] = set()
        self._unverified_values: dict[str, str] = {}
        self._resolve_depth = 0

    def next_step(self) -> StepDecision:
        if self.termination in {"WRITE_FAILED", "REPLAN_FAILED", "UNVERIFIED_EFFECT", "REPAIR_BUDGET"}:
            return StepDecision("STOP", reason_codes=(self.termination,), answer=self.last_text)
        if self.unverified and not self._recover_listed:
            self._recover_listed = True
            if any(self._fact(node_id) == "schedule.reminder" for node_id in self.unverified):
                return self._record(StepDecision("OBSERVE", (ToolCall("schedule_list", {}),), ("UNVERIFIED",)))
            return self._finish("UNVERIFIED", "RECOVER")
        if self.unverified:
            return self._finish("UNVERIFIED", "RECOVER")
        if self.before_decision is not None:
            for notice in self.before_decision(self.now, self.nodes):
                if notice.notice_id not in {item.notice_id for item in self.notices}:
                    self.notices.append(notice)
        verified, _, _ = goal_report(self.belief, self.receipts, self.goal_pairs)
        ctx = DecideContext(
            policy=self.evidence_policy,
            goal_verified=verified,
            now=self.now,
            risk=self.risk,
            observe_budget=self.observe_budget,
            replan_budget=self.replan_budget,
            observes_used=self.observes_used,
            replans_used=self.replans_used,
            refreshed_nodes=frozenset(self.refreshed),
            pending_notices=tuple(self.notices),
            acknowledged_notice_ids=frozenset(self.acknowledged),
            unverified_node_ids=tuple(self.unverified),
            replanned_notice_ids=frozenset(self.replanned),
        )
        decision = decide(self.belief, self.nodes, ctx)
        self.now += 1
        record = {
            "kind": decision.kind,
            "reason_codes": list(decision.reason_codes),
            "target_nodes": list(decision.target_nodes),
            "observation_keys": list(decision.observation_keys),
            "notice_ids": list(decision.notice_ids),
            "goal_verified": verified,
        }
        if decision.kind == "STOP":
            self.termination = decision.reason_codes[0] if decision.reason_codes else "STOP"
            self.decisions.append(record)
            return StepDecision("STOP", reason_codes=(self.termination,), answer=self.last_text, meta=record)
        if decision.kind == "RECOVER":
            self.termination = "UNVERIFIED"
            self.decisions.append(record)
            return StepDecision("RECOVER", reason_codes=("UNVERIFIED",), meta=record)
        if decision.kind == "REPLAN":
            self.decisions.append(record)
            targets = set(decision.target_nodes)
            if targets and targets <= self._closed_writes:
                return self._finish("EVIDENCE_UNKNOWN", "STOP")
            if self.replans_used >= self.replan_budget:
                return self._finish("REPLAN_BUDGET", "STOP")
            return StepDecision("REPLAN", reason_codes=tuple(decision.reason_codes), meta=record)
        if decision.kind == "OBSERVE":
            self.decisions.append(record)
            if self._stop_repeated_unknown(decision):
                return self._continue_after_close()
            calls = self._observe_calls(decision.observation_keys)
            if not calls:
                return self._finish("OBSERVE_BUDGET" if self.observes_used >= self.observe_budget else "EMPTY_OBSERVATION", "STOP")
            if set(decision.reason_codes) & REFRESH_REASONS:
                self.refreshed.update(decision.target_nodes)
            return StepDecision("OBSERVE", tuple(calls), tuple(decision.reason_codes), meta=record)
        node = _node(self.nodes, decision.target_nodes)
        self.decisions.append(record)
        if node is None:
            return self._finish("NO_NODE", "STOP")
        if node.action == "read_fact":
            key = str(node.args.get("fact_key") or "")
            if self.observes_used >= self.observe_budget:
                return self._finish("OBSERVE_BUDGET", "STOP")
            tool, arguments = self.read_binding(key)
            call = ToolCall(tool, arguments, f"read-{node.id}")
            self._pending[call.call_id] = {"op": "read", "fact_key": key, "node_id": node.id}
            return StepDecision("CONTINUE", (call,), tuple(decision.reason_codes), meta=record)
        if node.action == "write_fact":
            fact_key = str(node.args.get("fact_key") or "")
            if fact_key in self.confirmed_writes:
                node.status = "DONE"
                return StepDecision("CONTINUE", reason_codes=("ALREADY_CONFIRMED",), meta=record)
            try:
                args = resolve_args(node, self.belief)
            except ResolveError:
                return self._finish("RESOLVE_FAILED", "STOP")
            value = args.get("value")
            if value is None:
                return self._finish("RESOLVE_FAILED", "STOP")
            value = str(value)
            blocked = self._revision_block(node, fact_key)
            if blocked is not None:
                return blocked
            tool, tool_args = self.write_binding(fact_key, value)
            call = ToolCall(tool, tool_args, f"write-{node.id}")
            self._pending[call.call_id] = {"op": "write", "fact_key": fact_key, "node_id": node.id, "value": value, "tool": tool}
            return StepDecision("CONTINUE", (call,), tuple(decision.reason_codes), meta=record)
        return self._finish("UNSUPPORTED_ACTION", "STOP")

    def on_result(self, call: ToolCall, content: str) -> None:
        pending = self._pending.pop(call.call_id, None)
        if call.name == "schedule_list" and pending is None:
            self._reconcile_reminder(content)
            return
        if pending is None:
            return
        if pending["op"] == "read":
            self.observes_used += 1
            outcome = self._apply_read(pending["fact_key"], content)
            if outcome is not None:
                for notice in self.notices:
                    if notice.fact_key == pending["fact_key"] and acknowledgement_allowed(outcome, notice):
                        self.acknowledged.add(notice.notice_id)
            node = _node(self.nodes, (pending["node_id"],))
            if node is not None and node.action == "read_fact":
                node.status = "DONE"
            if outcome is not None and outcome.current is not None and outcome.current.status == "VALID":
                self._settled_unknown.discard(pending["fact_key"])
            else:
                self._settled_unknown.add(pending["fact_key"])
            return
        self._finish_write(pending, content)

    def apply_replan(self, decision: StepDecision) -> None:
        if self.evidence_policy == "B4" and self.replan_fn is not None:
            self.replans_used += 1
            try:
                fresh = self.replan_fn()
            except (OSError, RuntimeError, TimeoutError, ValueError, KeyError, TypeError):
                self.termination = "REPLAN_FAILED"
                self._stop_answer = self.last_text
                return
            done = {node.id: node for node in self.nodes if node.status == "DONE"}
            merged: list[PlanNode] = []
            seen: set[str] = set()
            for node in fresh:
                merged.append(done.get(node.id, node))
                seen.add(node.id)
            for node in self.nodes:
                if node.status == "DONE" and node.id not in seen:
                    merged.insert(0, node)
            self.nodes = merged
            self.replanned.update(decision.meta.get("notice_ids") or [])
            return
        result = repair_plan(
            self.nodes,
            decision.meta.get("target_nodes") or [],
            {},
            "local",
            unverified_effects=tuple(self.unverified),
            confirmed_writes=tuple(self.confirmed_writes),
        )
        self.replans_used += 1
        if result.mode == "stopped":
            self.termination = result.reason
            self._stop_answer = self.last_text
            return
        self.nodes = result.nodes
        self.replanned.update(decision.meta.get("notice_ids") or [])

    def _revision_block(self, node: PlanNode, fact_key: str):
        """写入前核对来源修订。对不上就不提交读取时看到的旧值。"""
        if self.revision_probe is None:
            return None
        raw_from = node.args.get("value_from")
        source_key = ""
        if isinstance(raw_from, dict):
            source_key = str(raw_from.get("fact_key") or "")
        if not source_key:
            return None
        from agent.application.conditional_write import WritePreconditions, judge_write

        expected = current_evidence(self.belief, source_key)
        window = False
        if self.commit_window_changed is not None:
            window = bool(self.commit_window_changed(source_key))
        verdict = judge_write(
            WritePreconditions(
                expected_source_revision="" if expected is None else str(expected.source_version),
                observed_source_revision=str(self.revision_probe(source_key)),
                expected_target_revision="",
                observed_target_revision="",
                cross_system=fact_key == "schedule.reminder",
                commit_window_changed=window,
            )
        )
        if verdict == "commit":
            return None
        self.last_text = "来源在读取之后变了，我没有提交当时看到的旧结果。"
        return self._finish("REVISION_CONFLICT", "STOP")

    def _observe_calls(self, keys: tuple[str, ...]) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for key in keys:
            if self.observes_used + len(calls) >= self.observe_budget:
                break
            try:
                tool, arguments = self.read_binding(key)
            except KeyError:
                continue
            call = ToolCall(tool, arguments, f"obs-{key}-{self.now}-{len(calls)}")
            self._pending[call.call_id] = {"op": "read", "fact_key": key, "node_id": ""}
            calls.append(call)
        return calls

    def _apply_read(self, fact_key: str, content: str):
        if effect_status(content) == "FAILED" and fact_key not in self.visible_facts and self.grounder is None:
            return None
        if self.grounder is not None:
            item = self.grounder(
                fact_key=fact_key,
                content=content,
                observed_at=max(self.now - 1, 0),
                ledger=self.revisions,
            )
        else:
            fallback = self.visible_facts.get(fact_key) or {}
            item = evidence_from_tool(
                fact_key=fact_key,
                content=content,
                observed_at=max(self.now - 1, 0),
                fallback_version=fallback.get("source_version"),
                fallback_value=fallback.get("value"),
                fallback_uri=fallback.get("source_uri") or "",
                ledger=self.revisions,
            )
        outcome = apply_observation(self.belief, item)
        if self.revisions.conflicted(fact_key):
            current = current_evidence(self.belief, fact_key)
            if current is not None:
                mark_status(self.belief, [current.id], "UNKNOWN")
        if getattr(self.grounder, "deadline_conflict", False):
            deadline = current_evidence(self.belief, "project.deadline")
            if deadline is not None:
                mark_status(self.belief, [deadline.id], "UNKNOWN")
        return outcome

    def _finish_write(self, pending: dict, content: str) -> None:
        status = _observed_status(content, pending["tool"])
        node = _node(self.nodes, (pending["node_id"],))
        if status == "CONFIRMED":
            self.receipts.append(
                {
                    "tool": pending["tool"],
                    "status": "CONFIRMED",
                    "fact_key": pending["fact_key"],
                    "value": pending["value"],
                }
            )
            self.confirmed_writes.add(pending["fact_key"])
            if node is not None:
                node.status = "DONE"
            return
        if status == "UNVERIFIED":
            self.unverified.append(pending["node_id"])
            self._unverified_values[pending["node_id"]] = pending["value"]
            self.termination = "UNVERIFIED"
            return
        self.termination = "WRITE_FAILED"

    def _finish(self, reason: str, kind: str) -> StepDecision:
        self.termination = reason
        return StepDecision(kind, reason_codes=(reason,), answer=self.last_text)

    def _record(self, decision: StepDecision) -> StepDecision:
        self.decisions.append({"kind": decision.kind, "reason_codes": list(decision.reason_codes)})
        return decision

    def _stop_repeated_unknown(self, decision) -> bool:
        """同一事实已经读出 UNKNOWN 后，不再为了 MISSING_EVIDENCE 重复读取。"""
        reasons = set(decision.reason_codes)
        if reasons != {"MISSING_EVIDENCE"}:
            return False
        keys = list(decision.observation_keys)
        if not keys or any(key not in self._settled_unknown for key in keys):
            return False
        for node_id in decision.target_nodes:
            node = _node(self.nodes, (node_id,))
            if node is not None and node.action == "write_fact" and node.status != "DONE":
                node.status = "BLOCKED"
                self._closed_writes.add(node.id)
        return True

    def _continue_after_close(self) -> StepDecision:
        self._resolve_depth += 1
        if self._resolve_depth > 8:
            return self._finish("EVIDENCE_UNKNOWN", "STOP")
        try:
            pending = [node for node in self.nodes if node.status in {"PENDING", "READY"}]
            if pending:
                return self.next_step()
            if self._closed_writes and not self.unverified:
                return self._finish("EVIDENCE_UNKNOWN", "STOP")
            return self.next_step()
        finally:
            self._resolve_depth -= 1

    def _reconcile_reminder(self, content: str) -> None:
        """只接受本 Run 的 operation id。同名提醒不能证明就是这次写入。"""
        from agent.harness.runtime import current_run

        run = current_run()
        if run is None or not self.unverified:
            return
        matched: list[str] = []
        for node_id in list(self.unverified):
            if self._fact(node_id) != "schedule.reminder":
                continue
            intent_id = ""
            for intent in run.intents:
                if intent.skill == "schedule_reminder" and intent.status == "unknown":
                    intent_id = intent.intent_id
                    break
            if not intent_id or intent_id not in (content or ""):
                continue
            matched.append(node_id)
            value = self._unverified_values.get(node_id, "")
            self.receipts.append(
                {
                    "tool": "schedule_reminder",
                    "status": "CONFIRMED",
                    "fact_key": "schedule.reminder",
                    "value": value,
                    "reconciled_by": intent_id,
                }
            )
            self.confirmed_writes.add("schedule.reminder")
            node = _node(self.nodes, (node_id,))
            if node is not None:
                node.status = "DONE"
        for node_id in matched:
            self.unverified.remove(node_id)
        if matched and not self.unverified and self.termination == "UNVERIFIED":
            self.termination = ""

    def _fact(self, node_id: str) -> str:
        node = _node(self.nodes, (node_id,))
        if node is None:
            return ""
        return str(node.args.get("fact_key") or "")


def _node(nodes: list[PlanNode], targets: tuple[str, ...]) -> PlanNode | None:
    if not targets:
        return None
    for node in nodes:
        if node.id == targets[0]:
            return node
    return None


def _observed_status(content: str, tool: str) -> str:
    status = effect_status(content)
    from agent.harness.runtime import current_run

    run = current_run()
    if run is None:
        return status
    for intent in reversed(run.intents):
        if intent.skill != tool:
            continue
        if intent.status == "unknown":
            return "UNVERIFIED"
        if intent.status == "failed":
            return "FAILED"
        break
    return status
