"""同步工具执行口。

调用方注入实现。本协议不判断这是 QQ、Coding CLI 还是 StateBench，
也不写账本、不做权限决策。
"""

from __future__ import annotations

from typing import Any, Protocol


class ToolExecutor(Protocol):
    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """执行一次工具调用，保持同步。

        返回字典至少包含 ``content``（str）。循环把这段文本写回 tool 消息。
        ``tool_call_id`` 不在这个签名里；需要它的适配器用 ``bind_call`` 接收。
        """
        ...
