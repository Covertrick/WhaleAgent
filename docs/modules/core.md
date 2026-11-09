# Core

## 1. 定位

Core 提供一次模型请求和工具协调，不是第二套权限系统，也不再拥有完整工具循环。步骤循环在 `agent/engine`。`agent_loop` 只组装 ReAct Policy。谁有权执行什么，由调用方注入的工具表和执行口决定。

## 2. 代码位置

| 文件 | 职责 |
|------|------|
| `agent/core/loop.py` | ReAct 兼容入口，内部调用 Engine |
| `agent/core/model_step.py` | 一次模型推理 |
| `agent/core/execute.py` | Hook、可选账本、调用 `dispatch` |
| `agent/core/llm.py` | `chat` / `chat_async` |
| `agent/core/coding_executor.py` | Coding CLI 执行口，`use_ledger=False` |
| `agent/contracts/executor.py` | `ToolExecutor` 协议 |

压缩、Coding 记忆、MCP 池、后台 bash 仍在 `agent/compaction`、`agent/memory`、`agent/mcp`、`agent/background`。它们不是 Harness。

## 3. 对外接口

```text
agent_loop(messages, active_request="", *, tools=None, handlers=None,
           system_provider=None, use_mcp=True, extract_memory=True,
           todo_reminder=True, max_rounds=None, executor=None) -> str | None
```

`executor is None` 时行为与重构前相同：调用 `execute_tool`。`ToolExecutor.execute(name, arguments) -> dict`，至少含 `content`。

`execute_tool(..., *, use_ledger=None)`。`None` 表示有 `current_run()` 才记账。`False` 只给 Coding 执行口。

## 4. 运行流程

每轮：后台结果、system、压缩、工具池、`chat`、无工具则停止，有工具则执行并写回。上下文溢出时 reactive compact，次数受 `MAX_REACTIVE_RETRIES` 限制。

QQ 传入自己的 tools、handlers、system，并传入 `HarnessExecutorAdapter`。CLI 传入 `CodingExecutorAdapter`，工具池仍由循环每轮用 `TASK_TOOLS` 拼出来。

## 5. 数据与副作用

循环改的是调用方给的 `messages`。账本只在 `execute_tool` 看见当前 Run 且没有 `use_ledger=False` 时写入。Coding 记忆提取在 `extract_memory=True` 时发生；QQ 关掉它。

## 6. 并发与恢复

循环本身是同步的。后台 bash 的完成通知由 `inject_background_results` 在下一轮注入。Run 的崩溃恢复不在 core，在 Harness。

## 7. 配置

模型名、地址、密钥在 `agent/config.py`（`MODEL_NAME`、`BASE_URL`、`API_KEY`）。循环没有自己的环境变量。QQ 的 `max_rounds` 由 `run_qq_agent` 默认传 6。StateBench B0 用 `experiment.yaml` 的 `max_rounds`。

## 8. 测试

B0 通过 `tests/statebench/test_d1_d3.py` 间谍 `loop.execute_tool`，确认不注入执行口时仍走默认函数。执行口测试在 `tests/harness/test_executor_port.py`。

## 9. 已知限制

- 默认路径仍会因为线程上残留的 Run 而记账。B0 和 `evals/harness.py` 依赖「不注入则旧行为」。
- `use_ledger=False` 不清除 contextvar。嵌套的直接 `execute_tool`（子 Agent）仍可能记账。
- 协议没有 `tool_call_id`。适配器用 `bind_call` 接收。没有 `bind_call` 的执行口仍可被调用，只是不知道调用 id。
- 非对象的工具参数在注入执行口时会变成 `{}`。默认路径仍把 `json.loads` 的结果原样交给 `execute_tool`。
- 没有新增 `ToolCall`、`ActionResult` 或频道无关的请求上下文。QQ 仍用 `ChatContext`。工具消息仍是现有 dict。

## 10. 维护规则

- 不要在 `loop.py` 里写「这个工具名走 Harness，那个走 Coding」。
- 不要把 `execute.py` 和 `harness/executor.py` 并成一个文件。前者是协调，后者是沙箱和 handler。
- 不要让 UNKNOWN 的不可逆动作在 `execute_tool` 里自动再调用 handler。
