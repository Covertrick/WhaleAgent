"""入口之间共用的协议。这里没有第二套 Runtime。"""

from agent.contracts.executor import ToolExecutor

__all__ = ["ToolExecutor"]
