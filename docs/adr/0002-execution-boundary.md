# ADR 0002：执行边界

## 状态

接受。

## 背景

QQ、Coding CLI 和 StateBench B0 都进入 `core/loop.py`，但权限不同。`core/execute.py` 在有当前 Run 时写账本，`harness/executor.py` 按沙箱策略调用 handler。两个名字相近，职责不重复。

## 决定

- 增加 `ToolExecutor` 协议。循环不按工具名选择实现。
- QQ 注入 `HarnessExecutorAdapter`，仍调用 `execute_tool`，账本顺序不变。
- Coding CLI 注入 `CodingExecutorAdapter`，`use_ledger=False`，不写 QQ 账本，工具保持同步。
- B0 不注入执行口，继续走默认 `execute_tool`。
- 不新增第二套权限检查，不把 UNKNOWN 的不可逆动作改成自动重试。
- 不把 `execute.py` 和 `executor.py` 合并。

## 后果

调用方必须显式选择执行口，否则默认路径仍会尊重线程上的 Run。`evals/harness.py` 和子 Agent 仍在默认路径上。`tool_call_id` 还不是协议参数，适配器用 `bind_call` 传递。
