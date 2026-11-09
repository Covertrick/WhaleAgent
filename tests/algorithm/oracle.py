"""测试辅助。只用于构造已知计划，不能进入决策器或 B0。"""

from __future__ import annotations

from collections.abc import Mapping

from agent.algorithms.planner import CompiledPlan, compile_plan, public_task_view


def compile_oracle_fixture(task: Mapping) -> CompiledPlan:
    plan = compile_plan(public_task_view(task))
    plan.plan_origin = "oracle_fixture"
    return plan
