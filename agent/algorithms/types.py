"""EGAA 的决策对象。这里没有 WorldTruth，隐藏状态不能进这个包。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Evidence:
    id: str
    fact_key: str
    value: Any
    source_id: str
    source_version: str
    observed_at: int
    status: str  # VALID / INVALID / UNKNOWN / SUPERSEDED
    observation_id: str = ""

    def __post_init__(self) -> None:
        if self.status not in ("VALID", "INVALID", "UNKNOWN", "SUPERSEDED"):
            raise ValueError(f"非法证据状态: {self.status}")
        if not self.observation_id:
            self.observation_id = self.id


@dataclass
class PlanNode:
    id: str
    action: str
    args: dict[str, Any] = field(default_factory=dict)
    depends_on_nodes: list[str] = field(default_factory=list)
    requires_evidence: list[str] = field(default_factory=list)
    status: str = "PENDING"  # PENDING / READY / DONE / BLOCKED
    irreversible: bool = False

    def __post_init__(self) -> None:
        if self.status not in ("PENDING", "READY", "DONE", "BLOCKED"):
            raise ValueError(f"非法计划状态: {self.status}")


@dataclass
class BeliefState:
    evidence: dict[str, Evidence] = field(default_factory=dict)
    observation_history: list[str] = field(default_factory=list)
    decision_step: int = 0
    slots: dict[str, str] = field(default_factory=dict)
    next_observation: int = 1


@dataclass
class Goal:
    """信念侧可核对的目标。评分器另用世界真值，不读这段。"""

    checks: tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class RiskRule:
    """验证集只允许选定一种规则，不能再拟合变化概率。"""

    mode: str  # evidence_age / before_irreversible
    max_age: int = 0

    def __post_init__(self) -> None:
        if self.mode not in ("evidence_age", "before_irreversible"):
            raise ValueError(f"非法风险规则: {self.mode}")
        if self.mode == "evidence_age" and self.max_age < 0:
            raise ValueError("证据年龄阈值不能为负")

    @property
    def label(self) -> str:
        if self.mode == "evidence_age":
            return f"max_age={self.max_age}"
        return "before_irreversible"


@dataclass(frozen=True)
class ChangeNotice:
    """一条已投递给决策器的变化通知。确认与否由调用方记录。"""

    notice_id: str
    fact_key: str
    received_at: int = 0


@dataclass
class DecideContext:
    policy: str
    goal_verified: bool
    now: int
    visible_changes: tuple[str, ...] = ()
    risk: RiskRule = field(default_factory=lambda: RiskRule("evidence_age", 10**9))
    observe_budget: int = 3
    replan_budget: int = 2
    observes_used: int = 0
    replans_used: int = 0
    refreshed_nodes: frozenset[str] = frozenset()
    pending_notices: tuple[ChangeNotice, ...] = ()
    acknowledged_notice_ids: frozenset[str] = frozenset()
    unverified_node_ids: tuple[str, ...] = ()
    replanned_notice_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Decision:
    kind: str  # CONTINUE / OBSERVE / REPLAN / RECOVER / STOP
    target_nodes: tuple[str, ...]
    reason_codes: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    threshold: str
    observation_keys: tuple[str, ...] = ()
    notice_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in ("CONTINUE", "OBSERVE", "REPLAN", "RECOVER", "STOP"):
            raise ValueError(f"非法决策: {self.kind}")
