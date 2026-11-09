"""CONTINUE / OBSERVE / REPLAN / STOP。阈值来自调用方，不在这里估计概率。"""

from __future__ import annotations

from dataclasses import replace

from agent.algorithms.evidence import ApplyResult, evidence_for
from agent.algorithms.invalidation import affected_ids, change_relation, scope_targets, used_fact_keys
from agent.algorithms.planner import next_executable, plan_errors
from agent.algorithms.policies import get_policy
from agent.algorithms.repair import pending_ids
from agent.algorithms.types import BeliefState, ChangeNotice, Decision, DecideContext, PlanNode
from agent.algorithms.validator import precondition


def _decision(
    kind: str,
    targets: list[str],
    reasons: list[str],
    evidence_ids: list[str],
    ctx: DecideContext,
    observation_keys: list[str] | None = None,
    notice_ids: list[str] | None = None,
) -> Decision:
    return Decision(
        kind,
        tuple(targets),
        tuple(reasons),
        tuple(evidence_ids),
        ctx.risk.label,
        tuple(observation_keys or ()),
        tuple(notice_ids or ()),
    )


def active_notices(ctx: DecideContext) -> list[ChangeNotice]:
    """尚未确认的通知。只传 visible_changes 时按事实键合成稳定 id。"""
    notices = [notice for notice in ctx.pending_notices if notice.notice_id not in ctx.acknowledged_notice_ids]
    covered = {notice.fact_key for notice in notices}
    for key in ctx.visible_changes:
        notice_id = f"visible:{key}"
        if key in covered or notice_id in ctx.acknowledged_notice_ids:
            continue
        notices.append(ChangeNotice(notice_id, key, ctx.now))
        covered.add(key)
    return notices


def acknowledge(ctx: DecideContext, notice_id: str) -> DecideContext:
    """调用方只在当前槽位成功更新后确认通知。本函数不检查观察是否成功。"""
    return replace(ctx, acknowledged_notice_ids=frozenset(ctx.acknowledged_notice_ids) | {notice_id})


def acknowledgement_allowed(result: ApplyResult, notice: ChangeNotice) -> bool:
    current = result.current
    return (
        result.effect in {"accepted", "replaced"}
        and current is not None
        and current.fact_key == notice.fact_key
        and current.status == "VALID"
    )


def _over_budget(ctx: DecideContext, kind: str) -> Decision | None:
    if kind == "OBSERVE" and ctx.observes_used >= ctx.observe_budget:
        return _decision("STOP", [], ["OBSERVE_BUDGET"], [], ctx)
    if kind == "REPLAN" and ctx.replans_used >= ctx.replan_budget:
        return _decision("STOP", [], ["REPLAN_BUDGET"], [], ctx)
    return None


def _needs_refresh(node: PlanNode, belief: BeliefState, ctx: DecideContext) -> bool:
    if node.id in ctx.refreshed_nodes:
        return False
    if ctx.risk.mode == "before_irreversible":
        return node.irreversible
    ages = []
    for evidence_id in node.requires_evidence:
        item = evidence_for(belief, evidence_id)
        if item is None or item.status != "VALID":
            continue
        ages.append(ctx.now - item.observed_at)
    return any(age >= ctx.risk.max_age for age in ages)


def _keys_for(node: PlanNode, belief: BeliefState) -> list[str]:
    keys: list[str] = []
    for evidence_id in node.requires_evidence:
        if evidence_id.startswith("ev:"):
            keys.append(evidence_id[3:])
            continue
        item = evidence_for(belief, evidence_id)
        if item is not None:
            keys.append(item.fact_key)
    value_from = node.args.get("value_from")
    if isinstance(value_from, dict) and value_from.get("fact_key"):
        keys.append(str(value_from["fact_key"]))
    unique: list[str] = []
    for key in keys:
        if key not in unique:
            unique.append(key)
    return unique


def _invalid_fact_keys(node: PlanNode, belief: BeliefState) -> list[str]:
    keys: list[str] = []
    for evidence_id in node.requires_evidence:
        item = evidence_for(belief, evidence_id)
        if item is not None and item.status == "INVALID":
            keys.append(item.fact_key)
    return keys


def decide(belief: BeliefState, nodes: list[PlanNode], ctx: DecideContext) -> Decision:
    spec = get_policy(ctx.policy)
    validation = plan_errors(nodes)
    if not validation.valid:
        return _decision("STOP", list(validation.node_ids), [validation.error_code], [], ctx)

    if ctx.unverified_node_ids:
        return _decision("RECOVER", list(ctx.unverified_node_ids), ["UNVERIFIED"], [], ctx)

    notices = active_notices(ctx)
    if spec.repair == "full_on_notice" and notices:
        fresh = [notice for notice in notices if notice.notice_id not in ctx.replanned_notice_ids]
        if fresh:
            budget = _over_budget(ctx, "REPLAN")
            if budget is not None:
                return budget
            return _decision(
                "REPLAN",
                pending_ids(nodes),
                ["ANY_NOTICE"],
                [],
                ctx,
                notice_ids=[item.notice_id for item in fresh],
            )

    if spec.observe == "risk" and notices:
        used = used_fact_keys(nodes, belief)
        unknown = [notice for notice in notices if change_relation(used, notice.fact_key) == "unknown"]
        relevant = [notice for notice in notices if change_relation(used, notice.fact_key) == "relevant"]
        if unknown:
            budget = _over_budget(ctx, "OBSERVE")
            if budget is not None:
                return budget
            facts: list[str] = []
            targets: list[str] = []
            for notice in unknown:
                scoped_facts, scoped_nodes = scope_targets(nodes, belief, notice.fact_key)
                for fact in scoped_facts:
                    if fact not in facts:
                        facts.append(fact)
                for node_id in scoped_nodes:
                    if node_id not in targets:
                        targets.append(node_id)
            return _decision(
                "OBSERVE",
                targets,
                ["UNKNOWN_SCOPE"],
                [],
                ctx,
                observation_keys=facts,
                notice_ids=[notice.notice_id for notice in unknown],
            )
        if relevant:
            budget = _over_budget(ctx, "OBSERVE")
            if budget is not None:
                return budget
            fact_keys = [notice.fact_key for notice in relevant]
            targets = affected_ids(nodes, belief, fact_keys)
            return _decision(
                "OBSERVE",
                targets,
                ["FACT_CHANGED"],
                [],
                ctx,
                observation_keys=fact_keys,
                notice_ids=[notice.notice_id for notice in relevant],
            )

    if ctx.goal_verified:
        return _decision("STOP", [], ["GOAL_MET"], [], ctx)

    node = next_executable(nodes)
    if node is None:
        if nodes and all(item.status == "DONE" for item in nodes):
            return _decision("STOP", [], ["GOAL_UNVERIFIED"], [], ctx)
        blocked = [item.id for item in nodes if item.status == "BLOCKED"]
        if blocked and spec.repair != "free":
            blocked_decision = _over_budget(ctx, "REPLAN")
            if blocked_decision is not None:
                return blocked_decision
            return _decision("REPLAN", blocked, ["BLOCKED_NODES"], [], ctx)
        return _decision("STOP", [], ["NO_PENDING"], [], ctx)

    if not spec.use_validator:
        return _decision("CONTINUE", [node.id], ["REACT_BASELINE"], [], ctx)

    state = precondition(node, belief)
    if state == "INVALID":
        budget = _over_budget(ctx, "REPLAN")
        if budget is not None:
            return budget
        if spec.repair == "local":
            targets = affected_ids(nodes, belief, _invalid_fact_keys(node, belief))
            if node.id not in targets:
                targets.insert(0, node.id)
        else:
            targets = pending_ids(nodes)
        return _decision(
            "REPLAN",
            targets,
            ["OBSERVED_INVALIDATION"],
            list(node.requires_evidence),
            ctx,
            observation_keys=_keys_for(node, belief),
        )

    if state == "UNKNOWN":
        budget = _over_budget(ctx, "OBSERVE")
        if budget is not None:
            return budget
        return _decision(
            "OBSERVE",
            [node.id],
            ["MISSING_EVIDENCE"],
            list(node.requires_evidence),
            ctx,
            observation_keys=_keys_for(node, belief),
        )

    if spec.observe == "always" and node.requires_evidence and node.id not in ctx.refreshed_nodes:
        budget = _over_budget(ctx, "OBSERVE")
        if budget is not None:
            return budget
        return _decision(
            "OBSERVE",
            [node.id],
            ["ALWAYS_REFRESH"],
            list(node.requires_evidence),
            ctx,
            observation_keys=_keys_for(node, belief),
        )

    if spec.observe == "risk" and node.requires_evidence and _needs_refresh(node, belief, ctx):
        budget = _over_budget(ctx, "OBSERVE")
        if budget is not None:
            return budget
        return _decision(
            "OBSERVE",
            [node.id],
            ["POTENTIALLY_STALE"],
            list(node.requires_evidence),
            ctx,
            observation_keys=_keys_for(node, belief),
        )

    return _decision(
        "CONTINUE",
        [node.id],
        ["PRECONDITIONS_HOLD"],
        list(node.requires_evidence),
        ctx,
    )
