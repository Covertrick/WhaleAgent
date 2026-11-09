"""有界计划图：编译公开任务视图、检查坏图、取下一节点。不搜索 HTN。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from agent.algorithms.evidence import current_evidence
from agent.algorithms.types import BeliefState, PlanNode

PUBLIC_FIELDS = (
    "task_id",
    "prompt",
    "source_key",
    "target_key",
    "readable",
    "writable",
    "goal_structure",
    "dependency_structure",
)
PRIVATE_FIELDS = frozenset(
    {
        "events",
        "initial_facts",
        "success",
        "constraints",
        "expected",
        "environment_event",
        "expected_world",
    }
)
SUPPORTED_ACTIONS = frozenset(
    {
        "read_fact",
        "write_fact",
        "read_meeting",
        "create_reminder",
    }
)


class PlanError(ValueError):
    """公开视图无法编译成合法计划。"""


class ResolveError(ValueError):
    """当前证据不能为写入参数提供值。"""


@dataclass(frozen=True)
class PlanValidationResult:
    valid: bool
    error_code: str
    node_ids: tuple[str, ...]
    details: tuple[str, ...]


@dataclass
class CompiledPlan:
    nodes: list[PlanNode]
    plan_origin: str
    unrelated_keys: tuple[str, ...] = ()

    def serialize(self) -> str:
        payload = {
            "plan_origin": self.plan_origin,
            "unrelated_keys": list(self.unrelated_keys),
            "nodes": [
                {
                    "action": node.action,
                    "args": node.args,
                    "depends_on_nodes": list(node.depends_on_nodes),
                    "id": node.id,
                    "irreversible": node.irreversible,
                    "requires_evidence": list(node.requires_evidence),
                    "status": node.status,
                }
                for node in self.nodes
            ],
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def public_task_view(task: Mapping) -> dict:
    """只保留 Agent 能从提示词和键名列表得到的字段。"""
    return {key: task[key] for key in PUBLIC_FIELDS if key in task}


def compile_plan(task: Mapping) -> CompiledPlan:
    private = sorted(PRIVATE_FIELDS.intersection(task))
    if private:
        raise PlanError("private_field:" + ",".join(private))
    goal = task.get("goal_structure")
    dependency = task.get("dependency_structure")
    source = str(task.get("source_key") or "")
    target = str(task.get("target_key") or "")
    if goal != "copy_final_source_to_target" or dependency != "read_then_write":
        raise PlanError("unsupported_structure")
    if not source or not target or source == target:
        raise PlanError("bad_fact_keys")
    readable = list(task.get("readable") or [])
    writable = list(task.get("writable") or [])
    if readable and source not in readable:
        raise PlanError("source_not_visible")
    if writable and target not in writable:
        raise PlanError("target_not_writable")
    nodes = [
        PlanNode(
            "read",
            "read_fact",
            args={"fact_key": source},
        ),
        PlanNode(
            "write",
            "write_fact",
            args={"fact_key": target, "value_from": {"fact_key": source}},
            depends_on_nodes=["read"],
            requires_evidence=[f"ev:{source}"],
            irreversible=True,
        ),
    ]
    validation = plan_errors(nodes)
    if not validation.valid:
        raise PlanError(validation.error_code)
    unrelated = tuple(key for key in readable if key != source)
    return CompiledPlan(nodes, "structured_task_compilation", unrelated)


def plan_errors(nodes: list[PlanNode]) -> PlanValidationResult:
    """先看原始列表上的非法图，再建索引查环。自依赖不算 PLAN_CYCLE。"""
    details: list[str] = []
    node_ids: list[str] = []
    seen: dict[str, int] = {}
    for node in nodes:
        if not node.id:
            details.append("empty_id")
            continue
        seen[node.id] = seen.get(node.id, 0) + 1
        if not node.action or node.action not in SUPPORTED_ACTIONS:
            details.append(f"unsupported_action:{node.id}")
            node_ids.append(node.id)
    for node_id, count in seen.items():
        if count > 1:
            details.append(f"duplicate_id:{node_id}")
            node_ids.append(node_id)
    known = set(seen)
    for node in nodes:
        if not node.id or seen.get(node.id, 0) != 1:
            continue
        for dep in node.depends_on_nodes:
            if dep == node.id:
                details.append(f"self_dependency:{node.id}")
                node_ids.append(node.id)
            elif dep not in known:
                details.append(f"missing_dependency:{dep}")
                node_ids.append(node.id)
    if details:
        return PlanValidationResult(False, "PLAN_INVALID", tuple(dict.fromkeys(node_ids)), tuple(details))
    cycled = _cycle_members(nodes)
    if cycled:
        return PlanValidationResult(False, "PLAN_CYCLE", tuple(cycled), ("cycle",))
    return PlanValidationResult(True, "", (), ())


def has_cycle(nodes: list[PlanNode]) -> bool:
    return bool(_cycle_members(nodes))


def _cycle_members(nodes: list[PlanNode]) -> list[str]:
    ids = [node.id for node in nodes if node.id]
    if len(ids) != len(set(ids)):
        return []
    children: dict[str, list[str]] = {node_id: [] for node_id in ids}
    known = set(ids)
    for node in nodes:
        for dep in node.depends_on_nodes:
            if dep == node.id or dep not in known:
                continue
            children[dep].append(node.id)
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []
    found: list[str] = []

    def walk(node_id: str) -> None:
        if found or node_id in visited:
            return
        if node_id in visiting:
            start = stack.index(node_id)
            found.extend(stack[start:])
            return
        visiting.add(node_id)
        stack.append(node_id)
        for child in children[node_id]:
            walk(child)
            if found:
                break
        stack.pop()
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in ids:
        walk(node_id)
        if found:
            break
    return found


def next_executable(nodes: list[PlanNode]) -> PlanNode | None:
    done = {node.id for node in nodes if node.status == "DONE"}
    for node in nodes:
        if node.status not in ("PENDING", "READY"):
            continue
        if all(dep in done for dep in node.depends_on_nodes):
            return node
    return None


def resolve_args(node: PlanNode, belief: BeliefState) -> dict:
    """执行前才从当前 VALID 证据取值。计划节点里的 value_from 保持不动。"""
    value_from = node.args.get("value_from")
    if not isinstance(value_from, dict) or not value_from.get("fact_key"):
        return dict(node.args)
    fact_key = str(value_from["fact_key"])
    current = current_evidence(belief, fact_key)
    if current is None:
        raise ResolveError(f"当前证据不可用: {fact_key}")
    resolved = {key: value for key, value in node.args.items() if key != "value_from"}
    resolved["value"] = current.value
    return resolved
