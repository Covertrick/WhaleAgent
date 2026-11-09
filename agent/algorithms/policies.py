"""五组对照只差这张开关表，不复制五套决策器。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PolicySpec:
    name: str
    use_validator: bool
    observe: str  # none / missing / risk / always
    repair: str  # free / regenerate / local / full_on_notice


POLICIES: dict[str, PolicySpec] = {
    spec.name: spec
    for spec in (
        PolicySpec("B0", False, "none", "free"),
        PolicySpec("B1", True, "missing", "regenerate"),
        PolicySpec("B2", True, "risk", "local"),
        PolicySpec("B3", True, "always", "local"),
        PolicySpec("B4", True, "risk", "full_on_notice"),
    )
}


def get_policy(name: str) -> PolicySpec:
    try:
        return POLICIES[name]
    except KeyError as exc:
        known = ", ".join(POLICIES)
        raise KeyError(f"未知策略 {name}。可选: {known}") from exc
