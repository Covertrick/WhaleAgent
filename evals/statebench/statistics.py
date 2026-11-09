"""配对差的区间。区间包含 0 时，调用方不得写成稳定提升。"""

from __future__ import annotations

import random


def paired_delta(
    left: list[bool],
    right: list[bool],
    *,
    rounds: int = 2000,
    seed: int = 0,
) -> dict[str, float | int | bool]:
    if len(left) != len(right) or not left:
        raise ValueError("两侧必须等长且非空")
    point = (sum(right) - sum(left)) / len(left)
    rng = random.Random(seed)
    size = len(left)
    samples: list[float] = []
    for _ in range(rounds):
        indexes = [rng.randrange(size) for _ in range(size)]
        delta = sum(right[i] - left[i] for i in indexes) / size
        samples.append(delta)
    samples.sort()
    low = samples[int(0.025 * (rounds - 1))]
    high = samples[int(0.975 * (rounds - 1))]
    return {
        "delta": point,
        "low": low,
        "high": high,
        "includes_zero": low <= 0 <= high,
        "n": size,
    }


def clustered_paired_delta(
    pairs_by_cluster: dict[str, list[tuple[bool, bool]]],
    *,
    rounds: int = 2000,
    seed: int = 0,
) -> dict[str, float | int | bool]:
    """按蓝图整组重抽样。同一个蓝图里的变体一起进入样本。"""
    clusters = sorted(pairs_by_cluster)
    flat = [pair for key in clusters for pair in pairs_by_cluster[key]]
    if not flat or not clusters:
        raise ValueError("聚类样本不能为空")

    def delta(items: list[tuple[bool, bool]]) -> float:
        return (sum(right for _left, right in items) - sum(left for left, _right in items)) / len(items)

    point = delta(flat)
    rng = random.Random(seed)
    samples: list[float] = []
    width = len(clusters)
    for _ in range(rounds):
        chosen = [clusters[rng.randrange(width)] for _ in range(width)]
        items = [pair for key in chosen for pair in pairs_by_cluster[key]]
        samples.append(delta(items))
    samples.sort()
    low = samples[int(0.025 * (rounds - 1))]
    high = samples[int(0.975 * (rounds - 1))]
    return {
        "delta": point,
        "low": low,
        "high": high,
        "includes_zero": low <= 0 <= high,
        "n": len(flat),
        "n_blueprints": len(clusters),
    }


def describe_scripted_comparison(result: dict[str, float | int | bool]) -> str:
    delta = float(result["delta"])
    if result["includes_zero"]:
        if delta > 0:
            trend = "样本上证据门控策略的任务成功率更高"
        elif delta < 0:
            trend = "样本上证据门控策略的任务成功率更低"
        else:
            trend = "样本上两边的任务成功率相同"
        return (
            f"{trend}，但本次规模下没有稳定差异的证据。"
            "比较对象是脚本化 ReAct 循环。线上大模型对照需要单独的 Live 实验。"
        )
    direction = "高于" if delta > 0 else "低于"
    return (
        f"在该冻结测试集和该脚本化配置下，证据门控策略的任务成功率{direction}脚本化 ReAct 循环，"
        "区间不含 0。这仍是受控环境里的规则比较。"
    )
