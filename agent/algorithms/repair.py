"""局部修复。已完成节点保持 DONE，即使调用方把它放进目标里。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from agent.algorithms.planner import PlanError, compile_plan, plan_errors
from agent.algorithms.types import PlanNode


def pending_ids(nodes: list[PlanNode]) -> list[str]:
    return [node.id for node in nodes if node.status != "DONE"]


def apply_replan_marks(nodes: list[PlanNode], target_ids: list[str] | tuple[str, ...]) -> list[str]:
    """把目标里尚未完成的节点标成 BLOCKED。返回实际改动的 id。"""
    wanted = set(target_ids)
    changed: list[str] = []
    for node in nodes:
        if node.id not in wanted or node.status == "DONE":
            continue
        if node.status != "BLOCKED":
            node.status = "BLOCKED"
            changed.append(node.id)
    return changed


@dataclass(frozen=True)
class RepairResult:
    nodes: list[PlanNode]
    mode: str
    changed_ids: tuple[str, ...]
    degraded: bool
    reason: str
    repair_kind: str


def _recompile(
    nodes: list[PlanNode],
    public_view: Mapping,
    mode: str,
    *,
    degraded: bool,
    confirmed_writes: tuple[str, ...],
) -> RepairResult:
    try:
        compiled = compile_plan(public_view)
    except PlanError:
        return RepairResult(nodes, "stopped", (), True, "REPLAN_FAILED", "stopped")
    done = {node.id: node for node in nodes if node.status == "DONE"}
    merged: list[PlanNode] = []
    changed: list[str] = []
    for node in compiled.nodes:
        if node.id in done:
            merged.append(done[node.id])
            continue
        if node.action == "write_fact" and str(node.args.get("fact_key") or "") in confirmed_writes:
            node.status = "DONE"
        merged.append(node)
        changed.append(node.id)
    seen = {node.id for node in merged}
    for node in nodes:
        if node.status == "DONE" and node.id not in seen:
            merged.insert(0, node)
    if not plan_errors(merged).valid:
        return RepairResult(nodes, "stopped", (), True, "REPLAN_FAILED", "stopped")
    return RepairResult(merged, mode, tuple(changed), degraded, "RECOMPILED", "full_replan")


def repair_plan(
    nodes: list[PlanNode],
    targets: list[str] | tuple[str, ...],
    public_view: Mapping,
    mode: str,
    *,
    replacements: dict[str, PlanNode] | None = None,
    unverified_effects: tuple[str, ...] = (),
    repair_budget_exhausted: bool = False,
    confirmed_writes: tuple[str, ...] = (),
) -> RepairResult:
    """局部修复只改未完成节点。未确认的副作用不能靠新节点绕过。"""
    if unverified_effects or repair_budget_exhausted:
        reason = "UNVERIFIED_EFFECT" if unverified_effects else "REPAIR_BUDGET"
        return RepairResult(list(nodes), "stopped", (), False, reason, "stopped")
    if mode in {"regenerated", "full"}:
        return _recompile(nodes, public_view, mode, degraded=False, confirmed_writes=confirmed_writes)

    wanted = set(targets)
    edited = [node for node in nodes]
    if replacements:
        edited = []
        for node in nodes:
            edited.append(replacements.get(node.id, node))
        for node_id, replacement in replacements.items():
            if all(node.id != node_id for node in edited):
                edited.append(replacement)
    changed: list[str] = []
    for node in edited:
        if node.status == "DONE":
            continue
        if node.id not in wanted and node.id not in (replacements or {}):
            continue
        if node.status != "PENDING":
            node.status = "PENDING"
            changed.append(node.id)
    if not plan_errors(edited).valid:
        return _recompile(nodes, public_view, "full", degraded=True, confirmed_writes=confirmed_writes)
    kind = "local_structural_repair" if replacements else "parameter_rebind"
    reason = "STRUCTURE_REPLACED" if replacements else "PARAMETER_REBIND"
    return RepairResult(edited, "local", tuple(changed), False, reason, kind)
