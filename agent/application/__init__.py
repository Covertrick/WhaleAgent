"""一次 Run 上的任务编排。

算法包只返回决策。本包选择策略、调用注入的执行器、把工具结果收成观察。
不读取 StateBench 的隐藏真值，也不自己记一套副作用账本。
"""

from agent.application.workflow import project_sync_requested, run_project_sync

__all__ = ["project_sync_requested", "run_project_sync"]
