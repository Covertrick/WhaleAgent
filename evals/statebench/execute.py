"""B1–B4 的回合执行器。评分只在结束后进行，决策看不到世界真值。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.algorithms.controller import acknowledgement_allowed, acknowledge, decide
from agent.algorithms.evidence import apply_observation, evidence_for, goal_supported_by_belief
from agent.algorithms.invalidation import change_relation, used_fact_keys
from agent.algorithms.planner import ResolveError, compile_plan, public_task_view, resolve_args
from agent.algorithms.repair import repair_plan
from agent.algorithms.types import BeliefState, ChangeNotice, DecideContext, Evidence, PlanNode, RiskRule
from evals.statebench.environment import Environment
from evals.statebench.episode import Episode, build_tools
from evals.statebench.protocol import budget_of, load_experiment, sha256_plan
from evals.statebench.scorer import score_episode
from evals.statebench.traces import TraceWriter

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"
REFRESH_REASONS = {"ALWAYS_REFRESH", "POTENTIALLY_STALE", "FACT_CHANGED", "UNKNOWN_SCOPE", "MISSING_EVIDENCE"}


def _versions(belief: BeliefState, evidence_ids: tuple[str, ...]) -> list[str | None]:
    found: list[str | None] = []
    for evidence_id in evidence_ids:
        item = evidence_for(belief, evidence_id)
        found.append(item.source_version if item is not None else None)
    return found


def _ages(belief: BeliefState, now: int) -> list[int]:
    ages: list[int] = []
    seen: set[str] = set()
    for item in belief.evidence.values():
        if item.fact_key in seen or item.status != "VALID":
            continue
        if belief.slots.get(item.fact_key) not in (None, item.id):
            continue
        seen.add(item.fact_key)
        ages.append(now - item.observed_at)
    return ages


def run_controlled(
    task: dict[str, Any],
    policy: str,
    *,
    risk: RiskRule | None = None,
    observe_budget: int | None = None,
    workspace: str | Path | None = None,
    trace_dir: str | Path | None = None,
) -> dict[str, Any]:
    experiment = load_experiment()
    limits = budget_of(experiment, observe=observe_budget)
    selected = risk or RiskRule("before_irreversible")
    if risk is None:
        from evals.statebench.protocol import risk_rule

        selected = risk_rule(experiment)
    spec = json.loads(json.dumps(task, ensure_ascii=False))
    view = public_task_view(spec)
    if workspace is None and trace_dir is None:
        base = RUNS / spec["task_id"] / policy / datetime.now().strftime("%Y%m%d%H%M%S%f")
    else:
        base = Path(workspace or RUNS / spec["task_id"] / policy)
    base.mkdir(parents=True, exist_ok=True)
    traces = TraceWriter(trace_dir or (base / "traces"))
    env = Environment(
        spec["initial_facts"],
        spec.get("events") or [],
        base / "world",
        readable=spec.get("readable"),
        writable=spec.get("writable"),
        env_only=spec.get("env_only"),
    )
    try:
        return _run(spec, view, policy, selected, limits, env, traces, experiment)
    finally:
        env.close()


def _run(
    spec: dict[str, Any],
    view: dict[str, Any],
    policy: str,
    risk: RiskRule,
    limits: dict[str, int],
    env: Environment,
    traces: TraceWriter,
    experiment: dict[str, Any],
) -> dict[str, Any]:
    snapshot_before = env.snapshot_token()
    compiled = compile_plan(view)
    nodes = compiled.nodes
    plan_hash = sha256_plan(compiled.serialize())
    belief = BeliefState()
    episode = Episode(spec, env, traces, llm="mock")
    _tools, handlers = build_tools(episode, budget=limits["tools"])
    receipts: list[dict[str, Any]] = []
    effect_attempts: list[dict[str, Any]] = []
    confirmed_writes: set[str] = set()
    unverified_ids: list[str] = []
    acknowledged: set[str] = set()
    replanned: set[str] = set()
    refreshed: set[str] = set()
    notices: list[ChangeNotice] = []
    decisions: list[dict[str, Any]] = []
    replans: list[dict[str, Any]] = []
    repair_kinds: list[str] = []
    ages: list[int] = []
    observes_used = 0
    replans_used = 0
    rejected_local = 0
    degrade_count = 0
    recovery_stops = 0
    evidence_actions = 0
    termination = "completed"
    goal_verified = False
    source_key = str(view.get("source_key") or "")
    target_key = str(view.get("target_key") or "")

    def stop(reason: str) -> None:
        nonlocal termination
        termination = reason

    for _round in range(limits["rounds"]):
        delivered = episode.before_decision([])
        for key in delivered:
            notice_id = f"notice:{key}"
            if all(item.notice_id != notice_id for item in notices):
                notices.append(ChangeNotice(notice_id, key, _round))
        goal_verified = goal_supported_by_belief(belief, source_key, target_key, receipts)
        ctx = DecideContext(
            policy=policy,
            goal_verified=goal_verified,
            now=_round,
            risk=risk,
            observe_budget=limits["observe"],
            replan_budget=limits["replan"],
            observes_used=observes_used,
            replans_used=replans_used,
            refreshed_nodes=frozenset(refreshed),
            pending_notices=tuple(notices),
            acknowledged_notice_ids=frozenset(acknowledged),
            unverified_node_ids=tuple(unverified_ids),
            replanned_notice_ids=frozenset(replanned),
        )
        decision = decide(belief, nodes, ctx)
        record = {
            "kind": "decision",
            "policy": policy,
            "decision_kind": decision.kind,
            "reason_codes": list(decision.reason_codes),
            "evidence_ids": list(decision.evidence_ids),
            "evidence_versions": _versions(belief, decision.evidence_ids),
            "threshold": decision.threshold,
            "observation_keys": list(decision.observation_keys),
            "notice_ids": list(decision.notice_ids),
            "target_nodes": list(decision.target_nodes),
            "goal_verified": goal_verified,
            "plan_hash": plan_hash,
        }
        decisions.append(record)
        traces.agent(record)
        ages.extend(_ages(belief, _round))
        if decision.kind == "STOP":
            stop(decision.reason_codes[0] if decision.reason_codes else "STOP")
            break
        if decision.kind == "RECOVER":
            recovery_stops += 1
            stop("UNVERIFIED")
            break
        if decision.kind == "REPLAN":
            if replans_used >= limits["replan"]:
                stop("REPLAN_BUDGET")
                break
            if unverified_ids:
                recovery_stops += 1
                stop("UNVERIFIED")
                break
            mode = "regenerated" if policy == "B1" else "full" if "ANY_NOTICE" in decision.reason_codes else "local"
            result = repair_plan(
                nodes,
                decision.target_nodes,
                view,
                mode,
                unverified_effects=tuple(unverified_ids),
                confirmed_writes=tuple(confirmed_writes),
            )
            replans_used += 1
            repair_kinds.append(result.repair_kind)
            if result.degraded:
                degrade_count += 1
            justified = "OBSERVED_INVALIDATION" in decision.reason_codes or _relevant(nodes, belief, decision.notice_ids, notices)
            replans.append({"reason": list(decision.reason_codes), "justified": justified, "repair_kind": result.repair_kind})
            if result.mode == "stopped":
                stop(result.reason)
                break
            nodes = result.nodes
            plan_hash = sha256_plan(compile_plan(view).serialize()) if result.repair_kind == "full_replan" else plan_hash
            for notice_id in decision.notice_ids:
                replanned.add(notice_id)
                notice = next((item for item in notices if item.notice_id == notice_id), None)
                if notice is not None and change_relation(used_fact_keys(nodes, belief), notice.fact_key) == "unrelated":
                    acknowledged.add(notice_id)
            continue
        if decision.kind == "OBSERVE":
            if observes_used >= limits["observe"]:
                stop("OBSERVE_BUDGET")
                break
            if not decision.observation_keys:
                stop("EMPTY_OBSERVATION")
                break
            for key in decision.observation_keys:
                if observes_used >= limits["observe"]:
                    stop("OBSERVE_BUDGET")
                    break
                outcome = _read(handlers, belief, key, _round, receipts)
                observes_used += 1
                repair_kinds.append("evidence_refresh")
                if outcome is None:
                    continue
                for notice in list(notices):
                    if notice.fact_key == key and acknowledgement_allowed(outcome, notice):
                        acknowledged.add(notice.notice_id)
            if set(decision.reason_codes) & REFRESH_REASONS:
                refreshed.update(decision.target_nodes)
            if termination in {"OBSERVE_BUDGET"}:
                break
            continue
        node = _node(nodes, decision.target_nodes)
        if node is None:
            stop("NO_NODE")
            break
        if node.action == "read_fact":
            if observes_used >= limits["observe"]:
                stop("OBSERVE_BUDGET")
                break
            key = str(node.args.get("fact_key") or source_key)
            _read(handlers, belief, key, _round, receipts)
            observes_used += 1
            if receipts and receipts[-1].get("status") == "CONFIRMED":
                node.status = "DONE"
            continue
        if node.action == "write_fact":
            if target_key in confirmed_writes:
                node.status = "DONE"
                continue
            try:
                args = resolve_args(node, belief)
            except ResolveError:
                rejected_local += 1
                traces.agent({"kind": "local_reject", "tool": "write_fact", "node": node.id})
                stop("RESOLVE_FAILED")
                break
            evidence_actions += 1
            repair_kinds.append("parameter_rebind")
            value = str(args.get("value"))
            attempt = _write(handlers, target_key, value)
            effect_attempts.append(attempt)
            if attempt["status"] == "CONFIRMED":
                confirmed_writes.add(target_key)
                receipts.append(attempt)
                node.status = "DONE"
                continue
            if attempt["status"] == "UNVERIFIED":
                unverified_ids.append(node.id)
                recovery_stops += 1
                stop("UNVERIFIED")
                break
            stop("WRITE_FAILED")
            break
        stop("UNSUPPORTED_ACTION")
        break
    else:
        stop("MAX_ROUNDS")

    score = score_episode(
        spec,
        env,
        episode.writes,
        checkpoint_reached=episode.checkpoint_applied,
        invalidation_log=None,
    )
    episode.finish(termination, reason=termination)
    traces.world({"kind": "score", **score, "goal_supported_by_belief": goal_verified})
    return {
        "task_id": spec["task_id"],
        "blueprint_id": spec.get("blueprint_id"),
        "scene": spec.get("scene"),
        "policy": policy,
        "llm": "mock",
        "score": score,
        "trace_dir": str(traces.directory),
        "tool_names": list(episode.tool_names),
        "tool_calls": episode.tool_calls,
        "snapshot_before": snapshot_before,
        "snapshot_after": env.snapshot_token(),
        "plan_hash": plan_hash,
        "decisions": decisions,
        "termination_reason": termination,
        "observe_count": observes_used,
        "replan_count": replans_used,
        "decision_count": len(decisions),
        "evidence_actions": evidence_actions,
        "degrade_count": degrade_count,
        "rejected_local": rejected_local,
        "unverified_effect_count": sum(1 for item in effect_attempts if item["status"] == "UNVERIFIED"),
        "recovery_stop_count": recovery_stops,
        "repair_kinds": repair_kinds,
        "replans": replans,
        "ages": ages,
        "goal_verified_final": goal_verified,
        "temperature": experiment.get("temperature"),
    }


def _relevant(nodes: list[PlanNode], belief: BeliefState, notice_ids: tuple[str, ...], notices: list[ChangeNotice]) -> bool:
    used = used_fact_keys(nodes, belief)
    chosen = {item.notice_id: item for item in notices}
    return any(change_relation(used, chosen[notice_id].fact_key) == "relevant" for notice_id in notice_ids if notice_id in chosen)


def _node(nodes: list[PlanNode], targets: tuple[str, ...]) -> PlanNode | None:
    if not targets:
        return None
    for node in nodes:
        if node.id == targets[0]:
            return node
    return None


def _read(handlers: dict[str, Any], belief: BeliefState, fact_key: str, now: int, receipts: list[dict[str, Any]]):
    raw = handlers["read_fact"](fact_key)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {"ok": False, "error": "bad_json"}
    if not data.get("ok"):
        receipts.append({"tool": "read_fact", "fact_key": fact_key, "status": "FAILED"})
        return None
    result = apply_observation(
        belief,
        Evidence(f"ev:{fact_key}", fact_key, str(data["value"]), "tool", str(data["version"]), now, "VALID"),
    )
    receipts.append(
        {
            "tool": "read_fact",
            "fact_key": fact_key,
            "status": "CONFIRMED",
            "value": str(data["value"]),
            "version": str(data["version"]),
        }
    )
    return result


def _write(handlers: dict[str, Any], fact_key: str, value: str) -> dict[str, Any]:
    raw = handlers["write_fact"](fact_key, value)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"tool": "write_fact", "fact_key": fact_key, "value": value, "status": "UNVERIFIED"}
    if data.get("ok"):
        return {"tool": "write_fact", "fact_key": fact_key, "value": value, "status": "CONFIRMED"}
    if data.get("error") in {None, ""}:
        return {"tool": "write_fact", "fact_key": fact_key, "value": value, "status": "UNVERIFIED"}
    return {"tool": "write_fact", "fact_key": fact_key, "value": value, "status": "FAILED", "error": data.get("error")}
