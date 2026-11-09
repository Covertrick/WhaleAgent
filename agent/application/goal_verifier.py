"""用已确认回执核对目标。不读取评分器或隐藏世界。"""

from __future__ import annotations

from agent.algorithms.evidence import current_evidence
from agent.algorithms.types import BeliefState


def branch_supported(belief: BeliefState, source_key: str, target_key: str, receipts: list[dict]) -> bool:
    current = current_evidence(belief, source_key)
    if current is None:
        return False
    for receipt in receipts:
        if (
            receipt.get("status") == "CONFIRMED"
            and receipt.get("fact_key") == target_key
            and receipt.get("value") == current.value
        ):
            return True
    return False


def goal_report(
    belief: BeliefState,
    receipts: list[dict],
    pairs: tuple[tuple[str, str], ...],
) -> tuple[bool, list[str], list[str]]:
    confirmed: list[str] = []
    open_items: list[str] = []
    for source_key, target_key in pairs:
        if branch_supported(belief, source_key, target_key, receipts):
            confirmed.append(target_key)
        else:
            open_items.append(target_key)
    return (not open_items), confirmed, open_items
