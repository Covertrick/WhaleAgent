"""按事实键把确定性影响传到未执行后继。无法判断的作用域不改成失效。"""

from __future__ import annotations

from agent.algorithms.types import BeliefState, PlanNode


def node_fact_keys(node: PlanNode, belief: BeliefState | None = None) -> set[str]:
    keys: set[str] = set()
    for evidence_id in node.requires_evidence:
        if evidence_id.startswith("ev:"):
            keys.add(evidence_id[3:])
        elif belief is not None:
            item = belief.evidence.get(evidence_id)
            if item is not None:
                keys.add(item.fact_key)
    value_from = node.args.get("value_from")
    if isinstance(value_from, dict) and value_from.get("fact_key"):
        keys.add(str(value_from["fact_key"]))
    if node.action == "read_fact" and node.args.get("fact_key"):
        keys.add(str(node.args["fact_key"]))
    return keys


def used_fact_keys(nodes: list[PlanNode], belief: BeliefState | None = None) -> set[str]:
    keys: set[str] = set()
    for node in nodes:
        keys |= node_fact_keys(node, belief)
    return keys


def change_relation(used: set[str], fact_key: str) -> str:
    if fact_key in used:
        return "relevant"
    parts = fact_key.split(".")
    for fact in used:
        fact_parts = fact.split(".")
        if len(parts) < len(fact_parts) and fact_parts[: len(parts)] == parts:
            return "unknown"
        if len(fact_parts) < len(parts) and parts[: len(fact_parts)] == fact_parts:
            return "unknown"
    return "unrelated"


def _children(nodes: list[PlanNode]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {node.id: [] for node in nodes}
    for node in nodes:
        for dep in node.depends_on_nodes:
            if dep in index:
                index[dep].append(node.id)
    return index


def seeds_for_facts(
    nodes: list[PlanNode],
    belief: BeliefState,
    fact_keys: tuple[str, ...] | list[str],
) -> list[str]:
    wanted = set(fact_keys)
    if not wanted:
        return []
    evidence_ids = {f"ev:{key}" for key in wanted}
    for item in belief.evidence.values():
        if item.fact_key in wanted:
            evidence_ids.add(item.id)
    return [node.id for node in nodes if evidence_ids.intersection(node.requires_evidence)]


def dependent_subgraph(nodes: list[PlanNode], origins: list[str]) -> list[str]:
    """原点加上全部可达后继，包含已经完成的中间节点。"""
    children = _children(nodes)
    order = [node.id for node in nodes]
    seen = set(origins)
    stack = list(origins)
    while stack:
        current = stack.pop()
        for child in children.get(current, []):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return [node_id for node_id in order if node_id in seen]


def affected_ids(
    nodes: list[PlanNode],
    belief: BeliefState,
    fact_keys: tuple[str, ...] | list[str],
) -> list[str]:
    used = used_fact_keys(nodes, belief)
    relevant = [key for key in fact_keys if change_relation(used, key) == "relevant"]
    reachable = dependent_subgraph(nodes, seeds_for_facts(nodes, belief, relevant))
    done = {node.id for node in nodes if node.status == "DONE"}
    return [node_id for node_id in reachable if node_id not in done]


def scope_targets(
    nodes: list[PlanNode],
    belief: BeliefState | None,
    fact_key: str,
) -> tuple[list[str], list[str]]:
    """未知作用域需要复查的事实键和未执行节点。空结果表示不是未知作用域。"""
    used = used_fact_keys(nodes, belief)
    if change_relation(used, fact_key) != "unknown":
        return [], []
    facts = [fact for fact in sorted(used) if change_relation({fact}, fact_key) == "unknown"]
    wanted = set(facts)
    node_ids = [
        node.id
        for node in nodes
        if node.status != "DONE" and node_fact_keys(node, belief).intersection(wanted)
    ]
    return facts, node_ids
