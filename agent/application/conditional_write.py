"""写入前的修订条件。同一存储可以拒绝旧值；跨系统只记录剩余竞态。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WritePreconditions:
    expected_source_revision: str
    observed_source_revision: str
    expected_target_revision: str
    observed_target_revision: str
    cross_system: bool
    commit_window_changed: bool = False


def judge_write(pre: WritePreconditions) -> str:
    """返回 commit、reject_source、reject_target 或 residual_race。

    跨系统写入即使检查通过，提交窗口里的再次变化也不能当成原子成功。
    """
    if pre.expected_source_revision != pre.observed_source_revision:
        return "reject_source"
    if not pre.cross_system and pre.expected_target_revision != pre.observed_target_revision:
        return "reject_target"
    if pre.cross_system and pre.commit_window_changed:
        return "residual_race"
    return "commit"
