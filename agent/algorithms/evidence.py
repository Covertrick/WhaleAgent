"""信念更新。只接受已经发生的观察，不接收世界真值。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from agent.algorithms.types import BeliefState, Evidence


@dataclass(frozen=True)
class ApplyResult:
    effect: str  # accepted / replaced / archived / conflict
    belief: BeliefState
    current: Evidence | None
    observation_id: str


def evidence_for(belief: BeliefState, evidence_id: str) -> Evidence | None:
    return belief.evidence.get(evidence_id)


def fact_evidence(belief: BeliefState, fact_key: str) -> list[Evidence]:
    return [item for item in belief.evidence.values() if item.fact_key == fact_key]


def current_evidence(belief: BeliefState, fact_key: str) -> Evidence | None:
    """只返回当前槽位上的 VALID。失效、未知和已替代都不算当前依据。"""
    slot = belief.slots.get(fact_key)
    if slot is not None:
        item = belief.evidence.get(slot)
        if item is not None and item.fact_key == fact_key and item.status == "VALID":
            return item
        return None
    matches = [item for item in fact_evidence(belief, fact_key) if item.status == "VALID"]
    if len(matches) == 1:
        return matches[0]
    return None


def _version_rank(version: str) -> int | None:
    if version.startswith("v") and version[1:].isdigit():
        return int(version[1:])
    return None


def _order(current: Evidence, incoming: Evidence) -> str:
    if current.source_version == incoming.source_version and current.value != incoming.value:
        return "conflict"
    left = _version_rank(current.source_version)
    right = _version_rank(incoming.source_version)
    if left is None or right is None:
        if current.source_version == incoming.source_version and current.value == incoming.value:
            return "duplicate"
        return "incomparable"
    if right > left:
        return "newer"
    if right < left:
        return "older"
    return "duplicate"


def _mint_observation_id(belief: BeliefState, item: Evidence, slot: str | None) -> str:
    candidate = item.observation_id
    occupied = candidate in belief.evidence or candidate == slot or candidate == item.id
    if not candidate or occupied:
        while True:
            candidate = f"obs:{item.fact_key}:{belief.next_observation:06d}"
            belief.next_observation += 1
            if candidate not in belief.evidence and candidate != slot:
                break
        return candidate
    belief.next_observation += 1
    return candidate


def _archive_status(status: str) -> str:
    if status == "INVALID":
        return "INVALID"
    return "SUPERSEDED"


def apply_observation(belief: BeliefState, item: Evidence) -> ApplyResult:
    """写入一条不可变观察。较旧的记录不能替换当前槽位。"""
    slot = belief.slots.get(item.fact_key)
    current = belief.evidence.get(slot) if slot else None
    observation_id = _mint_observation_id(belief, item, slot)
    if current is None:
        slot = item.id or f"ev:{item.fact_key}"
        stored = replace(item, id=slot, observation_id=observation_id)
        belief.evidence[slot] = stored
        if observation_id != slot:
            belief.evidence[observation_id] = stored
        belief.slots[item.fact_key] = slot
        belief.observation_history.append(observation_id)
        return ApplyResult("accepted", belief, stored, observation_id)

    order = _order(current, item)
    if order == "newer":
        archived = replace(current, id=current.observation_id, status=_archive_status(current.status))
        belief.evidence[current.observation_id] = archived
        stored = replace(item, id=slot or current.id, observation_id=observation_id, status=item.status)
        belief.evidence[stored.id] = stored
        if observation_id != stored.id:
            belief.evidence[observation_id] = stored
        belief.slots[item.fact_key] = stored.id
        belief.observation_history.append(observation_id)
        return ApplyResult("replaced", belief, stored, observation_id)

    status = "UNKNOWN" if order in {"conflict", "incomparable"} else "SUPERSEDED"
    archived = replace(item, id=observation_id, observation_id=observation_id, status=status)
    belief.evidence[observation_id] = archived
    belief.observation_history.append(observation_id)
    effect = "conflict" if order == "conflict" else "archived"
    return ApplyResult(effect, belief, current, observation_id)


def mark_status(belief: BeliefState, evidence_ids: list[str], status: str) -> list[str]:
    changed: list[str] = []
    for evidence_id in evidence_ids:
        item = belief.evidence.get(evidence_id)
        if item is None or item.status == status:
            continue
        item.status = status
        changed.append(evidence_id)
    return changed


def goal_supported_by_belief(
    belief: BeliefState,
    source_key: str,
    target_key: str,
    receipts: list[dict],
) -> bool:
    """只看当前有效证据和已确认的写入回执。不能读取世界真值或评分断言。"""
    current = current_evidence(belief, source_key)
    if current is None:
        return False
    for receipt in receipts:
        if (
            receipt.get("tool") == "write_fact"
            and receipt.get("status") == "CONFIRMED"
            and receipt.get("fact_key") == target_key
            and receipt.get("value") == current.value
        ):
            return True
    return False


def goal_met_by_belief(checks: tuple[tuple[str, object], ...], belief: BeliefState) -> bool:
    """只看当前 VALID 证据。已替代的旧值不会让这里变成 True。"""
    for fact_key, expected in checks:
        current = current_evidence(belief, fact_key)
        if current is None or current.value != expected:
            return False
    return True
