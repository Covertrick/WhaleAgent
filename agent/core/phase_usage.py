"""按阶段记下模型用量。接口没返回的字段保持空，不补成 0。"""

from __future__ import annotations

from dataclasses import dataclass

CANONICAL_PHASES = (
    "goal_parse",
    "plan_generate",
    "evidence_extract",
    "plan_repair",
    "react_step",
    "result_summarize",
)

_PHASE_ALIAS = {
    "plan": "plan_generate",
    "extract": "evidence_extract",
    "react": "react_step",
    "repair": "plan_repair",
    "summarize": "result_summarize",
    "goal": "goal_parse",
}


@dataclass(frozen=True)
class ModelCallUsage:
    phase: str
    prompt_tokens: int | None
    completion_tokens: int | None
    cached_tokens: int | None


def canonical_phase(raw: str) -> str:
    name = (raw or "").strip() or "unspecified"
    mapped = _PHASE_ALIAS.get(name, name)
    if mapped in CANONICAL_PHASES:
        return mapped
    return "unspecified"


def _optional_int(payload: dict, key: str) -> int | None:
    if key not in payload or payload[key] is None:
        return None
    return int(payload[key])


def usage_from_api(usage: dict | None, *, phase: str) -> ModelCallUsage:
    payload = dict(usage or {})
    cached = _optional_int(payload, "cached_tokens")
    details = payload.get("prompt_tokens_details")
    if cached is None and isinstance(details, dict):
        cached = _optional_int(details, "cached_tokens")
    return ModelCallUsage(
        phase=canonical_phase(phase),
        prompt_tokens=_optional_int(payload, "prompt_tokens"),
        completion_tokens=_optional_int(payload, "completion_tokens"),
        cached_tokens=cached,
    )
