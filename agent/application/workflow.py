"""项目资料与截止事项：同一条计划上的检索、草稿和提醒。"""

from __future__ import annotations

import re

from agent.algorithms.types import PlanNode
from agent.application.catalog import GOAL_PAIRS
from agent.application.run_driver import DriverResult, run_driver

_VERSIONED = re.compile(r"^(资料|截止)\s+(v\d+)\s*[:：]\s*(.+)$")


def project_sync_nodes() -> list[PlanNode]:
    """草稿可重写，提醒不可逆。两条分支只共享「先读到对应证据」。"""
    return [
        PlanNode("read_materials", "read_fact", args={"fact_key": "project.materials"}),
        PlanNode("read_deadline", "read_fact", args={"fact_key": "project.deadline"}),
        PlanNode(
            "write_draft",
            "write_fact",
            args={"fact_key": "note.draft", "value_from": {"fact_key": "project.materials"}},
            depends_on_nodes=["read_materials"],
            requires_evidence=["ev:project.materials"],
            irreversible=False,
        ),
        PlanNode(
            "write_reminder",
            "write_fact",
            args={"fact_key": "schedule.reminder", "value_from": {"fact_key": "project.deadline"}},
            depends_on_nodes=["read_deadline"],
            requires_evidence=["ev:project.deadline"],
            irreversible=True,
        ),
    ]


def project_sync_requested(text: str) -> bool:
    """只接跨资料和截止事项的请求。普通闲聊仍走模型循环。"""
    raw = text or ""
    if "整理" not in raw and "同步" not in raw:
        return False
    return any(token in raw for token in ("资料", "会议", "截止", "提醒", "待办", "Vault", "vault"))


def message_facts(text: str) -> dict[str, dict[str, str]]:
    """用户在同一条消息里写明的版本和值。这是公开文本，不是评分答案。"""
    found: dict[str, dict[str, str]] = {}
    labels = {"资料": "project.materials", "截止": "project.deadline"}
    for line in (text or "").splitlines():
        matched = _VERSIONED.match(line.strip())
        if matched is None:
            continue
        fact_key = labels[matched.group(1)]
        found[fact_key] = {
            "source_version": matched.group(2),
            "value": matched.group(3).strip(),
            "source_uri": "user_message",
        }
    return found


def run_project_sync(
    executor,
    *,
    user_text: str,
    policy: str = "B2",
    before_decision=None,
    mode: str = "scripted",
) -> DriverResult:
    """scripted 使用固定计划，供离线测试。live 让模型生成计划，校验失败就不执行。"""
    nodes = project_sync_nodes()
    grounder = None
    if mode == "live":
        from agent.algorithms.planner import PlanError
        from agent.application.grounding import model_grounder
        from agent.policies.planning import compile_model_plan

        try:
            nodes = compile_model_plan(user_text, schema_hint=_LIVE_SCHEMA)
        except (PlanError, RuntimeError, TimeoutError, OSError) as exc:
            from agent.application.run_driver import DriverResult

            return DriverResult(
                reply=f"计划没有通过检查，我没有开始写入。{exc}",
                termination="PLAN_INVALID",
            )
        grounder = model_grounder()
    pairs = GOAL_PAIRS
    if mode == "live":
        pairs = (("meeting.notes", "note.draft"), ("project.deadline", "schedule.reminder"))
    return run_driver(
        nodes,
        executor,
        policy=policy,
        goal_pairs=pairs,
        user_text=user_text,
        visible_facts=message_facts(user_text),
        before_decision=before_decision,
        grounder=grounder,
    )


_LIVE_SCHEMA = """
事实键只允许 meeting.notes、project.deadline、note.draft、schedule.reminder。
read_fact 读取前两个键。note.draft 用 value_from 指向 meeting.notes，irreversible 为 false。
schedule.reminder 用 value_from 指向 project.deadline，irreversible 为 true。
write_fact 的 args 只能是 {"fact_key":"...","value_from":{"fact_key":"..."}}，不能写 value。
写入值来自工具原文的抽取结果，不要在计划里填写具体待办或截止时间。
输出 {"nodes":[{"id","action","args","depends_on_nodes","requires_evidence","irreversible"}]}。
"""
