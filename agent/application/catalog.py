"""项目资料工作流的工具对照。计划节点仍使用 read_fact / write_fact。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ReadBinding:
    fact_key: str
    tool: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class WriteBinding:
    fact_key: str
    tool: str
    arguments_for: Callable[[str], dict[str, Any]]


READS: dict[str, ReadBinding] = {
    "meeting.notes": ReadBinding(
        "meeting.notes",
        "search_vault",
        {"query": "项目会议资料"},
    ),
    "project.materials": ReadBinding(
        "project.materials",
        "search_vault",
        {"query": "项目会议资料"},
    ),
    "project.deadline": ReadBinding(
        "project.deadline",
        "search_vault",
        {"query": "项目截止时间"},
    ),
}

WRITES: dict[str, WriteBinding] = {
    "note.draft": WriteBinding(
        "note.draft",
        "write_vault_draft",
        lambda value: {"topic": "项目待办草稿", "body": value},
    ),
    "schedule.reminder": WriteBinding(
        "schedule.reminder",
        "schedule_reminder",
        lambda value: {"title": "项目截止", "due_at": value, "category": "todo"},
    ),
}

GOAL_PAIRS = (
    ("project.materials", "note.draft"),
    ("project.deadline", "schedule.reminder"),
)


def read_call(fact_key: str) -> tuple[str, dict[str, Any]]:
    binding = READS[fact_key]
    return binding.tool, dict(binding.arguments)


def write_call(fact_key: str, value: str) -> tuple[str, dict[str, Any]]:
    binding = WRITES[fact_key]
    return binding.tool, binding.arguments_for(value)
