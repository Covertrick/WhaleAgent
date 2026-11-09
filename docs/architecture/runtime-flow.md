# QQ 一条消息

群里没有 @ 的消息不进模型，也不开 Run。短句拦截命中后直接回复。下面是会打开 Run 的那一条：先选定并冻结一个 Policy，再进入同一个 Engine。

```text
OneBot 事件
  → router 去重 / 入队
  → run_qq_agent
       1. consume_notices：把上次 UNKNOWN 的说明拿出来
       2. start_run：冻结 skill_snapshot、harness_rev、当时的 guardrails.md
       3. build_tools(ctx)：只有 tools.qq
       4. HarnessExecutorAdapter(handlers)
       5. 选定一次 Policy 并 bind_policy
          项目资料协同：egaa@2，run_project_sync(mode=live)
          其它消息：react@1，agent_loop 只负责组装 ReActPolicy
       6. agent.engine 重复调用这个 Policy，并执行它返回的工具
  → 循环里每次 tool_call：
       bind_call(tool_call_id)   # 适配器忽略换进来的工具池
       adapter.execute(name, arguments)
         → execute_tool          # 不传 use_ledger=False
              PreToolUse
              begin_intent       # 见下方原子顺序
              dispatch           # sandbox_policy
              complete_intent    # SUCCEEDED / FAILED / UNKNOWN
  → 项目资料任务把决策写到 harness/decisions/{run_id}.json，trace_for 按同一个 Run ID 读出
  → finish Run
  → 若本轮有 UNKNOWN，说明拼在回复前面
  → channel.send 把文本发出去
```

## 账本顺序

`begin_intent` 比「先落一条 STARTED 再检查权限」更严，测试依赖这个顺序，重构没有改：

1. 没有契约且 Run 要求契约：直接返回拒绝文本，不创建 intent。
2. 不可逆、guardrails 含「禁止自动重试」或「一律禁止重试」、同参数已经 FAILED 或 UNKNOWN：返回口语说明，不创建新 intent。
3. 同参数已经 SUCCEEDED，且效果类是幂等或可重试：返回上次摘要，不再执行。
4. 其余情况：写入 `STARTED` 并落盘，然后才 `dispatch`。
5. 超时 → `UNKNOWN`。普通异常 → `FAILED`。返回文本以 `UNKNOWN:` 开头 → `UNKNOWN`。
6. 不可逆的 UNKNOWN 恢复动作是 `ASK_USER`。`spoken_unknown` 告诉用户不会自动再做。适配器不会在同一次 `execute` 里再调 handler。

进程死在 `STARTED` 之后：下次启动 `recover_open_runs` 把该意图标成 `UNKNOWN`，只推一句说明。可重试类也要用户再发一次，不会在启动时把模型循环重跑。

## 执行口不改这条路径的含义

循环自己不判断「这个名字走 QQ 还是 Coding」。QQ 入口把 `HarnessExecutorAdapter` 交进去。适配器固定使用 `build_tools` 当时的 handlers，所以即使有人误把 MCP 池 bind 进来，QQ 也不会因此获得 bash。

没有活动 Run 时，这个适配器直接拒绝，不会悄悄退化成无账本执行。

## 相关代码

- `agent/channel/run.py`
- `agent/channel/router.py`
- `agent/harness/runtime.py` 的 `start_run` / `begin_intent` / `complete_intent` / `recover_open_runs`
- `agent/core/loop.py`
- `agent/core/execute.py`
- `agent/harness/executor.py`
- `agent/harness/effect.py`
