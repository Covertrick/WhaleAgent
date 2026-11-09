"""Engine 与 Policy 之间的一步决策。这里没有账本，也没有世界真值。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""


@dataclass(frozen=True)
class StepDecision:
    kind: str  # CONTINUE / OBSERVE / REPLAN / RECOVER / STOP
    tool_calls: tuple[ToolCall, ...] = ()
    reason_codes: tuple[str, ...] = ()
    answer: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in {"CONTINUE", "OBSERVE", "REPLAN", "RECOVER", "STOP"}:
            raise ValueError(f"非法步骤: {self.kind}")
