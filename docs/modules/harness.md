# Harness

## 1. 定位

Harness 是 QQ 侧唯一被授权写副作用账本的运行时。它解决的是：一次用户消息对应一次 Run，工具在执行前留下 `STARTED`，崩溃后能把未确认的动作说成 `UNKNOWN`，并且按效果类决定能不能再做。

它不解析 OneBot，不决定 EGAA 的观察或重规划，也不给 Coding CLI 记账。沙箱执行在 `executor.dispatch`，协调在 `core/execute.py`。两个都留着。

## 2. 代码位置

| 文件 | 职责 |
|------|------|
| `agent/harness/runtime.py` | 开 Run、冻结快照、`begin_intent` / `complete_intent`、启动时收口 |
| `agent/harness/store.py` | Run、Intent、会话通知的原子 JSON |
| `agent/harness/effect.py` | 效果类、Run/Intent 状态、UNKNOWN 文案 |
| `agent/harness/skill_contract.py` | `SkillManifest` 字段 |
| `agent/harness/qq_skills.py` | 内置 QQ 工具的契约表 |
| `agent/harness/registry.py` | 插件索引、引用计数、按 Run 冻结版本 |
| `agent/harness/executor.py` | precondition / sandbox_policy / postcondition |
| `agent/harness/adapters.py` | `HarnessExecutorAdapter`，仍调用 `execute_tool` |
| `agent/harness/trace.py` | 按 `run_id` 组装轨迹 |
| `agent/harness/sandbox/` | L1 AST、L2 子进程 |
| `agent/harness/evolve/` | 只允许改三个约束文件，并在执行期拦住不可逆重试 |

## 3. 对外接口

- `get_runtime()` / `HarnessRuntime.start_run` / `finish` / `recover_open_runs` / `consume_notices`
- `current_run()`：contextvar。`execute_tool` 用它决定要不要记账
- `SkillManifest`、`QQ_SKILL_MANIFESTS`、`assert_covers_qq_tools`
- `dispatch(name, args, handler, snapshot) -> (text, usage)`
- `HarnessExecutorAdapter(handlers).execute(name, arguments) -> {"content": str}`

QQ 入口在 `start_run` 之后把适配器交给 `agent_loop`。不要绕过适配器直接在频道里调用领域函数来完成「模型请求的工具」。拦截短句是另一条路径，在 `channel/intercept.py`，不进 Run 的工具循环。

## 4. 运行流程

见 [runtime-flow.md](../architecture/runtime-flow.md)。摘要：

`start_run` 把内置契约和插件索引进快照。`begin_intent` 在落 `STARTED` 之前可以拒绝。`dispatch` 按快照里的 `sandbox_policy` 走进程内、L1 或 L2。`complete_intent` 写终态。`finish` 时若仍有 UNKNOWN 意图，整次 Run 记为 UNKNOWN。

## 5. 数据与副作用

落盘在 `agent/.runtime/qq/harness/`（`QQ_RUNTIME` 下的 `harness/runs` 与 `sessions`）。Run 上还有冻结的 `guardrail_text`。领域数据（记忆、文件、Vault）由工具 handler 自己写，Harness 只记录意图和结果摘要。

插件在 Run 存活期间被引用计数钉住，引用为 0 才允许卸载。

## 6. 并发与恢复

当前 Run 放在 contextvar 里，按线程可见。`recover_open_runs`：

- 只有规划、没有已开始的副作用 → `ABORTED`
- 有 `STARTED` / `PLANNED` 的意图 → 标 `UNKNOWN`，按 `recovery_for` 给一句说明
- 已经是 `UNKNOWN` 的 Run 不重复刷通知

`RecoveryAction.RETRY` / `RETRY_SAME_KEY` 的说明里写了自动重试上限，但实现是「请用户再发一次」，启动时不会重跑循环。不可逆默认 `ASK_USER`，不自动再做。

## 7. 配置

效果类和权限写在 `qq_skills.py` 与插件 `manifest.yaml`，不是环境变量。约束文本在运行时目录的 `guardrails.md`、`skill_notes.md`、`postconditions.py`。`evolve/whitelist.py` 只允许改这三个文件。

`blocks_auto_retry` 仅当效果类是 `irreversible` 且冻结的 guardrails 含「禁止自动重试」或「一律禁止重试」时，才拒绝同参数的再次执行。

## 8. 测试

- `python -m agent.smoke_test` 里的 `test_harness_p0`：契约名一致、无契约拒绝、崩溃后 UNKNOWN、`ASK_USER`
- `python -m unittest tests.harness -v`：执行口仍走账本，Coding 适配器不写账本，不可逆 UNKNOWN 在一次 execute 内不重试
- `python -m unittest tests.architecture -v`：Harness 不 import channel / OneBot

## 9. 已知限制

- `HarnessExecutorAdapter` 在没有当前 Run 时直接拒绝。这只影响新适配器；直接调用 `execute_tool` 的旧路径仍是「有 Run 才记账」。
- 适配器不接受 bind 进来的另一份 handlers。QQ 若同时 `use_mcp=True`，模型可能看见多出来的工具名，执行仍用构造时的表。正式入口把 `use_mcp` 设为 False。
- `use_ledger=False` 不会从 QQ 适配器传入。
- 自修改不能改权限表、`effect_class`、沙箱或适配器协议。

## 10. 维护规则

- 新的 QQ 工具必须同时出现在 `QQ_SKILL_MANIFESTS` 和 `tools/qq.py` 的 schema / handlers。名字不一致时 `build_tools` 和架构测试会失败。
- 不要把 Coding 的 bash / MCP 加进 QQ handlers。
- 不要在 Harness 里 import `agent.channel` 或 OneBot。
- 不要把 UNKNOWN 的不可逆动作改成自动重试。
- 改 `begin_intent` 的拒绝顺序之前，先看 `smoke_test` 和 `tests/harness`。
