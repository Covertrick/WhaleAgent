# 沙箱

## 1. 定位

沙箱执行不可信代码。它不决定 QQ 用户能不能调用某个内置工具。内置 QQ 工具的 `sandbox_policy` 是 `none`，在进程内调用 handler。

## 2. 代码位置

- `agent/harness/executor.py`：按快照选择 `none` / `ast` / `process`
- `agent/harness/sandbox/ast_sandbox.py`：L1
- `agent/harness/sandbox/process_sandbox.py`：L2 子进程，超时后杀掉，工作目录限制在沙箱内
- `agent/harness/sandbox/runner.py`：L2 入口，限制网络和越权读
- `agent/harness/evolve/enforce.py`：`postconditions.py` 的 `check(result)` 在 L1 里跑

Coding 的 bash 不走这套 L2。它在 `tools/base.py` 里用 `subprocess`，工作目录是 `WORKDIR`，并有自己的危险命令拒绝列表。

## 3. 对外接口

`dispatch` 返回 `(文本, usage)`。`run_process` / `run_ast` 返回 `SandboxResult`（`ok`、`output`、`exit_code`、`usage`）。

策略来自快照。参数里 `untrusted=True`，或名字以 `run_` 开头且带 `code` 而策略仍是 `none` 时，`dispatch` 会升到 `process`。

## 4. 运行流程

`execute_tool` 在账本允许之后调用 `dispatch`。`process` 缺代码则 precondition 失败。`ast` 同样要求 `code`。`none` 调用 handler，再跑 postcondition。postcondition 失败的文本以 `postcondition 失败` 开头，`execute_tool` 把它记为 `FAILED`。

## 5. 数据与副作用

L2 的默认工作目录是 `FILES_DIR/_sandbox`。调用方可传 `cwd`。L2 的网络限制在 runner 里，不在 QQ 的 `web_search` 上。`web_search` 是普通 handler。

## 6. 并发与恢复

L2 超时由 `run_process` 处理。`execute_tool` 把 `TimeoutError` 记为 UNKNOWN（仅当这次调用走了账本）。进程沙箱在 Windows 上会尽量把子进程放进 Job；失败则忽略，这是 `process_sandbox.py` 里的现有行为。

## 7. 配置

快照字段 `sandbox_policy`：`none`、`ast`、`process`。`dispatch` 从参数读 `timeout`，缺省 5 秒，只用于 `process` 分支。Coding bash 的等待在 `base.py` 里是 120 秒，与这里不是同一个数。

## 8. 测试

冒烟调用 `run_ast` 和 `run_process`。本次没有改沙箱策略。

## 9. 已知限制

- `skill_contract.py` 的注释仍写「P0 只记录，执行仍在进程内」。`dispatch` 已经会按策略走 L1/L2。注释和执行不一致的地方，以 `executor.py` 为准。
- postcondition 读取失败时 `dispatch` 吞掉异常并放过。这是现有行为。

## 10. 维护规则

- 不要用沙箱代替 QQ 契约检查。没有契约的工具在 `begin_intent` 就被拒绝。
- 不要把 Coding bash 改成 L2，除非单独的变更说明为什么，并保住现有拒绝列表。
