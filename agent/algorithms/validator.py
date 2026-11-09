"""三值前置条件。缺少证据、未知和已替代都不会被当成成立。"""

from __future__ import annotations

from agent.algorithms.types import BeliefState, PlanNode


def precondition(node: PlanNode, belief: BeliefState) -> str:
    if not node.requires_evidence:
        return "VALID"
    saw_unknown = False
    for evidence_id in node.requires_evidence:
        item = belief.evidence.get(evidence_id)
        if item is not None and item.status == "INVALID":
            return "INVALID"
        if item is None or item.status != "VALID":
            saw_unknown = True
    if saw_unknown:
        return "UNKNOWN"
    return "VALID"
