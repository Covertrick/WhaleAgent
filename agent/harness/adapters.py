"""QQ Harness 执行口。

仍然调用 ``core.execute.execute_tool``，因此顺序保持：

PreToolUse → begin_intent（无契约 / 幂等 / 禁止重试可在落账前拒绝）
→ 落盘 STARTED → dispatch → complete_intent。

本适配器不另写一套权限或重试。handlers 固定为构造时传入的那份，
不接受循环事后换上的工具池，避免 bash / MCP 从 Coding 池灌进 QQ。
"""

from __future__ import annotations

from typing import Any, Callable


class HarnessExecutorAdapter:
    def __init__(self, handlers: dict[str, Callable[..., str]]) -> None:
        self._handlers = dict(handlers)
        self._tool_call_id = ""

    def bind_call(self, tool_call_id: str, handlers: dict | None = None) -> None:
        """只记下调用 id。忽略 handlers，见模块说明。"""
        _ = handlers
        self._tool_call_id = tool_call_id or ""

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from agent.core.execute import execute_tool
        from agent.harness.runtime import current_run

        if current_run() is None:
            return {"content": "Error: 没有活动的 Harness Run，已拒绝执行。"}
        text = execute_tool(
            name,
            arguments or {},
            self._handlers,
            tool_call_id=self._tool_call_id,
        )
        return {"content": text}
