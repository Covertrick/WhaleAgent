# 架构

项目资料任务和普通 QQ 消息共用一次 Harness Run，并在 Run 开始时冻结一个 Policy。两者都进入 `agent.engine`。StateBench v1 用冻结 Runner 复现旧结果；v2 使用同一个 Engine 和模拟适配器。评分不读 NapCat，也不把隐藏状态交给策略。v1 结果见 [evaluation/egaa-v1-results.md](./evaluation/egaa-v1-results.md)。

系统划分见 [architecture/overview.md](./architecture/overview.md)。下面是线上执行的操作摘要。

```text
线上 QQ
  channel → harness Run → 冻结 egaa@2 或 react@1
        → agent.engine 重复调用这一个 Policy
        → execute_tool → 账本 / 沙箱 / 领域工具

离线评测
  v1：冻结 Runner。B1–B4 调用 decide，B0 仍是脚本化 agent_loop
  v2：同一个 Engine + Policy + 模拟执行适配器
  评分器都在循环结束后读真值，不走 QQ 入口
```

QQ 是适配器。一次用户消息对应一次 Harness Run，并且只冻结一个 Policy。工具调用先写 intent 账本，再按技能快照里的沙箱策略执行。

```text
NapCat / OneBot
        │
        ▼
channel/          收发、去重、限流、群缓存、文件静默入库、拦截短句
        │  run_qq_agent
        ▼
harness/runtime   打开 Run，冻结技能版本和当时的 guardrails.md
        │
        ▼
core/loop         压缩、chat、tool_calls（QQ 关闭 MCP 与 Coding 记忆提取）
        │
        ▼
core/execute      PreToolUse → begin_intent（拒绝，或先 STARTED 落盘）→ executor.dispatch
        │
        ├─ sandbox none     内置 QQ 工具（tools/qq.py）
        ├─ ast / process    快照要求 L1/L2，或参数带 untrusted/code
        └─ plugin handler   注册表按 Run 冻结的版本取函数
        │
        ▼
complete_intent → SUCCEEDED / FAILED / UNKNOWN
finish Run；UNKNOWN 的口语说明在下一条消息前发给用户
```

## 依赖方向

- `channel/` 解析 OneBot，不定义 `effect_class`。
- `harness/` 不读 OneBot 字段。会话键是 `qq:{user_id}:{group_id|private}`。
- `knowledge/`、`files/`、`vault/`、`schedules/` 不直接发 QQ 消息。`life/monitor.py` 的定时速递会调用 `channel/send.py`，这是唯一的领域包例外。其余发送走 `channel/send.py` 或工具里拿到的 OneBot 客户端。调度器 `agent/scheduler.py` 也会发送，它不在领域包里。
- `plugins/` 只提供 `manifest.yaml` 和 `register` / `unregister`。加载、引用计数、版本快照在 `harness/registry.py`。

## 一次 QQ 消息

1. `python -m agent` 启动时 `recover_open_runs`：还停在 `STARTED` 的意图标成 `UNKNOWN`；只有规划、没有已开始副作用的 Run 标成 `ABORTED`。两类都不会自动把模型循环重跑。可重试类也要用户再发一次。
2. `run_qq_agent` 先取出该会话积压的 UNKNOWN 说明，再 `start_run`。Run 上冻结 `skill_snapshot`、`harness_rev` 和当时的 `guardrails.md` 全文。
3. `agent_loop` 调模型。QQ 传入自己的 tools/handlers、`HarnessExecutorAdapter` 和 system，`use_mcp=False`，`extract_memory=False`，`todo_reminder=False`，默认最多 6 轮。适配器仍调用 `execute_tool`，不另写权限。
4. `execute_tool` 在调用 handler 之前把 intent 刷成 `STARTED` 并落盘。无契约、幂等命中、或 guardrails 禁止的不可逆重试，会在落账前拒绝。
5. 同一 Run、同一参数：幂等或可重试技能若已经 `SUCCEEDED`，直接返回上次摘要，不再执行。
6. 不可逆技能若本 Run 的 guardrails 含「禁止自动重试」或「一律禁止重试」，且同参数已经 `FAILED` 或 `UNKNOWN`，不再执行，返回口语说明。
7. `sandbox_policy` 为 `process` 走 L2 子进程，为 `ast` 走 L1。内置 QQ 工具默认 `none`，在进程内调用。
8. `none` 策略下，若运行时目录里的 `postconditions.py` 定义了 `check(result)`，就在 L1 沙箱里验证输出。失败把这次工具记成 `FAILED`。
9. 超时记 `UNKNOWN`；普通异常记 `FAILED`。handler 返回以 `UNKNOWN:` 开头时也升级为 `UNKNOWN`。
10. 循环结束 `finish`。若本轮仍有 `UNKNOWN` 意图，整次 Run 记为 `UNKNOWN`。说明在回复前拼给用户。

Coding CLI（`python -m agent.main`）不调用 `start_run`。它注入 `CodingExecutorAdapter`，`execute_tool(..., use_ledger=False)`，因此即使线程上残留 Run 也不写这次 QQ 账本。工具仍是 bash、文件、任务图、MCP 和 `skills/`，并且保持同步。StateBench B0 不注入执行口，继续走默认 `execute_tool`。

## 落盘 `agent/.runtime/qq/`

| 路径 | 内容 |
|------|------|
| `harness/runs/*.json` | Run 与 intent 账本 |
| `harness/sessions/` | 按会话积压的 UNKNOWN 说明 |
| `harness/guardrails.md` | 当前已生效约束（Run 启动时复制进 `guardrail_text`） |
| `harness/skill_notes.md` | 可晋升的技能说明 |
| `harness/postconditions.py` | 输出检查，须定义 `check(result)` |
| `harness/snapshots/` | 约束快照 |
| `harness/active_rev.txt` | 当前约束版本 |
| `harness/evolve_log.jsonl` | 晋升、丢弃、回滚 |
| `memory/` `files.db` `vault.db` `vector/` `usage.db` | 领域数据 |

自修改只允许上面三个文本：`guardrails.md`、`skill_notes.md`、`postconditions.py`。权限表、`effect_class`、沙箱实现、Adapter 协议不在白名单里。

## 算法包与评测包

`agent/algorithms` 只放证据、计划图、三值前置条件和五组策略开关。它不 import `channel`。`evals/statebench` 持有可重置真值和隐藏事件；`apply_checkpoint` 只把 `notify=True` 的事实键交出去。

B0 到 B4 共用 `controller.decide`。差别写在 `policies.py` 的一张表里：要不要验证、何时观察、局部修复还是整计划重做。已有的 Harness 账本、插件和沙箱不另写一套。Coding CLI 的 A–F 评测仍在 `evals/`，不充当这组对照。
