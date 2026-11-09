"""Coding CLI 执行口。

走同一条 ``execute_tool``，但 ``use_ledger=False``：不写 QQ Run 账本，
也不因为线程上残留的 Run 而套用 QQ 契约。权限仍是 Coding 的 PreToolUse。
工具保持同步。handlers 由循环每轮 bind，因为 MCP 池会变。
"""

from __future__ import annotations

from typing import Any


class CodingExecutorAdapter:
    def __init__(self) -> None:
        self._handlers: dict = {}
        self._tool_call_id = ""

    def bind_call(self, tool_call_id: str, handlers: dict | None = None) -> None:
        self._tool_call_id = tool_call_id or ""
        if handlers is not None:
            self._handlers = handlers

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from agent.core.execute import execute_tool

        text = execute_tool(
            name,
            arguments or {},
            self._handlers,
            tool_call_id=self._tool_call_id,
            use_ledger=False,
        )
        return {"content": text}
