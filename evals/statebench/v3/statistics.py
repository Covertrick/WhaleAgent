"""按蓝图聚类的配对 Bootstrap。没有真实对照结果时不要拿它宣称实验结论。"""

from __future__ import annotations

import random
from collections import defaultdict


def clustered_bootstrap(
    rows: list[dict],
    *,
    left: str,
    right: str,
    iterations: int = 5000,
    seed: int = 20261110,
) -> dict:
    """rows 需要 blueprint_id、policy、success、observations、cost。"""
    grouped: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        grouped[row["blueprint_id"]][row["policy"]].append(row)
    keys = [key for key, item in grouped.items() if left in item and right in item]
    if not keys:
        return {"defined": False, "reason": "no_pairs"}
    rng = random.Random(seed)
    success_deltas = []
    observation_deltas = []
    cost_deltas = []
    for _ in range(iterations):
        draw = [rng.choice(keys) for _ in keys]
        success_deltas.append(_mean_delta(grouped, draw, left, right, "success"))
        observation_deltas.append(_mean_delta(grouped, draw, left, right, "observations"))
        cost_deltas.append(_mean_delta(grouped, draw, left, right, "cost"))
    return {
        "defined": True,
        "pairs": len(keys),
        "iterations": iterations,
        "seed": seed,
        "success_delta": _interval(success_deltas),
        "observation_delta": _interval(observation_deltas),
        "cost_delta": {"defined": False} if any(item is None for item in cost_deltas) else _interval(cost_deltas),
    }


def _mean_delta(grouped, draw, left: str, right: str, field: str) -> float | None:
    total = 0.0
    for key in draw:
        left_values = [item[field] for item in grouped[key][left]]
        right_values = [item[field] for item in grouped[key][right]]
        if any(value is None for value in left_values + right_values):
            return None
        left_mean = sum(float(value) for value in left_values) / len(left_values)
        right_mean = sum(float(value) for value in right_values) / len(right_values)
        total += left_mean - right_mean
    return total / len(draw)


def _interval(samples: list[float]) -> dict:
    ordered = sorted(samples)
    lower = ordered[int(0.025 * (len(ordered) - 1))]
    upper = ordered[int(0.975 * (len(ordered) - 1))]
    return {"mean": sum(samples) / len(samples), "lower": lower, "upper": upper}
