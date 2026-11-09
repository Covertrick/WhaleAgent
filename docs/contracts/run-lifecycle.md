# Run 生命周期

一次 QQ 模型回合是一个 Run。Coding CLI 和 StateBench 不开这个 Run。

## 状态

`RunStatus`：`created`、`planning`、`tool_pending`、`tool_running`、`awaiting_confirm`、`unknown`、`succeeded`、`failed`、`cancelled`、`aborted`。

终态是 `succeeded`、`failed`、`cancelled`、`aborted`。其余算未结案，包括 `unknown`。

`start_run` 实际写入的初始状态是 `planning`，不是 `created`。`tool_pending` 和 `awaiting_confirm` 在枚举里，当前 `runtime.py` 没有把 Run 设成这两值。确认类工具（`delete_file` 的效果类是 `requires_confirm`）的交互在频道的 pending 状态里，不在这个枚举的赋值点上。

`IntentStatus`：`planned`、`started`、`succeeded`、`failed`、`unknown`。`begin_intent` 创建的记录直接是 `started`。

## 正常结束

`finish(SUCCEEDED)` 时如果还有 UNKNOWN 意图，状态改成 `UNKNOWN`。回复文本另存。然后释放插件引用，并清掉 contextvar。

## 崩溃

`recover_open_runs` 只在启动时走。规则见 [harness.md](../modules/harness.md)。它不重新调用模型。

## 和执行口的关系

QQ 的 `HarnessExecutorAdapter` 要求 `current_run()` 非空。Run 由 `run_qq_agent` 在调用 `agent_loop` 之前 `start_run`。循环结束或异常时 `finish`。

Coding 执行口即使看见残留的 Run，也不给这次调用写 intent。
