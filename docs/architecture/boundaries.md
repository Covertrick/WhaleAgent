# 依赖边界

允许的依赖是「谁可以调用谁」。禁止的依赖用 `tests/architecture` 的 AST 扫描卡住。扫描看不到 `importlib`，这和 `evals/statebench/imports_scan.py` 的限制一样。

## 允许

| 从 | 到 | 原因 |
|----|----|------|
| `channel` | `application`、`harness`、`core.loop`、`tools.qq` | 项目资料任务交给应用层；其它消息打开 Run 后进入模型循环 |
| `application` | `algorithms`、`harness` | 调用 `decide`，再调用已经打开的执行器 |
| `core.loop` | `contracts.ToolExecutor`、默认的 `execute_tool` | 循环只调用注入的执行口 |
| `harness.adapters` | `core.execute` | QQ 执行口必须走现有账本顺序 |
| `core.coding_executor` | `core.execute` | Coding 执行口复用同一协调函数，但关掉账本 |
| `core.execute` | `harness.runtime`、`harness.executor` | 有 Run 才记账；沙箱在 dispatch |
| `tools.qq` | `knowledge`、`schedules`、`user_files`、`vault`、`search` | 工具实现 |
| `evals.statebench` | `agent.algorithms`、临时的 `agent.core.loop`（仅 B0） | 评测驱动决策或脚本循环 |
| 领域包 | `agent.channel.trust`、`group_cache`、`file_cache` | 现有代码如此：包装不可信文本、读群窗口和近期文件 |
| `agent/life/monitor.py` | `agent.channel.send` | 唯一例外：定时速递。见该文件 `register_digest_job` |
| 根上的 `scheduler.py` | `channel.onebot`、`channel.send` | 催办到点发送。它不是领域包 |

## 禁止

| 从 | 不得 | 测试 |
|----|------|------|
| `agent.algorithms` | `agent.channel`、OneBot、`evals.statebench`、`agent.harness`、`sqlite3` | `test_algorithms_do_not_import_channel_onebot_statebench_or_harness` |
| `agent.harness` | `agent.channel` 或 OneBot 客户端 | `test_harness_does_not_import_channel_or_onebot` |
| `knowledge` `files` `vault` `schedules` `life` | `agent.channel.send`、`agent.channel.onebot`、`agent.channel.client_ref` | `test_domains_do_not_send_except_digest_job` |
| `agent.channel` | `agent.algorithms` | `test_channel_does_not_import_algorithms` |
| `agent.application` | `agent.channel`、OneBot、`evals.statebench` | `test_application_does_not_import_channel_or_statebench` |

`harness/evolve/whitelist.py` 里的字符串 `"onebot"` 是自修改文本的禁词，不是 import。扫描用 AST，不会把它当成依赖。

领域包里对 `trust` / `group_cache` / `file_cache` 的引用保持原样。收紧它们会改变线上行为，这次没有动。

## 不共享的东西

- QQ 工具名单和 Coding 工具名单。`FORBIDDEN_ON_QQ` 含 `bash`、`connect_mcp`、任务图工具。
- QQ 的 Run 账本和 Coding CLI。CLI 注入 `CodingExecutorAdapter`，`use_ledger=False`。
- StateBench 的世界真值。`algorithms` 只看见调用方递进来的信念、通知事实键和计划节点。
- 隐藏事件。`Environment.apply_checkpoint` 只把 `notify=True` 的事实键交出去。

## 根上的基础设施

这些文件留在 `agent/` 根上，不迁进 `agent/domains/`：

`http_client.py`、`embedding.py`、`search.py`、`config.py`、`scheduler.py`、`timeutil.py`、`user_files.py`、`calendar_sync.py`。

它们被 QQ 工具、频道或调度同时使用。搬进领域目录不会消掉职责重叠，只会改掉一串导入。
