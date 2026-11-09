# Channel

## 1. 定位

频道是 QQ 适配器：听 OneBot、去重、限流、群缓存、短句拦截、把 Harness 的回复发出去。它不定义 `effect_class`，也不调用 `agent.algorithms`。

## 2. 代码位置

`agent/channel/`。职责表见 [files.md](../files.md) 的频道一节。入口装配在 `agent/__main__.py`。模型循环的包一层是 `run.py` 的 `run_qq_agent`。

## 3. 对外接口

- `python -m agent` 启动 OneBot、恢复未完成 Run、调度和可选控制台
- `run_qq_agent(ctx, history, max_rounds=6) -> str`
- `ChatContext`：用户、群、文本。存储键和召回范围是它的属性
- `safe_send_msg`：令牌桶、抖动、熔断、分片

## 4. 运行流程

`router` 处理事件。未 @ 的群消息只进缓存和静默入库。@ 和私聊进队列，然后 `run_qq_agent`。流程细节在 [runtime-flow.md](../architecture/runtime-flow.md) 和 [logic-flow.md](../logic-flow.md)。

`run_qq_agent` 在 `start_run` 之后构造 `HarnessExecutorAdapter`，然后选定一次 Policy。项目资料冻结 `egaa@2`，其它消息冻结 `react@1`。随后都进入 Engine。ReAct 路径的 `use_mcp=False`，不用 Coding 的记忆提取和 todo 提醒。

## 5. 数据与副作用

短期历史在 `channel/session.py`。删除确认在 `pending.py`，重启即空。发送走 OneBot。工具副作用不在频道里直接做，除了拦截短句和 URL 预取（预取结果包进 `<untrusted_content>`）。

## 6. 并发与恢复

`job_queue` 有界。`QQ_AGENT_CONCURRENCY` 限制同时处理的条数。用户冷却、发送桶和熔断在 `rate_limit.py`。Harness 的 UNKNOWN 说明在下一条进入 `run_qq_agent` 时被 `consume_notices` 取走。

## 7. 配置

OneBot、主人 QQ、限流、早报、健康检查等都在 `agent/config.py` 读取环境变量。名字以代码为准，例如 `ONEBOT_WS_URL`、`QQ_OWNER_QQ`、`QQ_AGENT_CONCURRENCY`。模板是 `agent/.env.example`。不要把真实 `.env` 读进文档或提交。

## 8. 测试

`tests/channel/test_async_ingress.py` 不连 NapCat。频道行为的其余部分在 `python -m agent.smoke_test` 的拦截、分片和工具白名单段。冒烟若因可选依赖失败，不要为了通过而去改断言。

## 9. 已知限制

- `channel/__init__.py` 会导入 `run.py`，而 `run.py` 导入 `tools.qq`。`tools.qq` 不再在导入期引用 `channel`，避免环。函数内部仍会按需引用 `client_ref`、`pending`、`trust`。
- 频道不感知算法。不要把 StateBench 的隐藏事件塞进提示词。

## 10. 维护规则

- 发消息走 `channel/send.py` 或工具拿到的客户端，不要在领域包里新加发送。
- 不要 import `agent.algorithms`。
- QQ 路径保持 `require_contract=True` 和 `HarnessExecutorAdapter`。
