# 领域

## 1. 定位

领域包保存 QQ 助手的用户数据：记忆、文件、Vault、催办、闪念和开销。它们不决定工具能不能跑，也不持有 Run。这次没有把它们挪进 `agent/domains/`。

`agent/vector` 是嵌入索引的存储实现，跟领域数据放在一起用，同样留在原处。

## 2. 代码位置

逐文件说明在 [files.md](../files.md) 的「领域包」一节。包名：

- `agent/knowledge`：按用户或群隔离的情景记忆、画像、知识卡片
- `agent/files`：下载、去重、标签、检索、发送前的记录
- `agent/schedules`：催办 SQLite 和提醒时间规则
- `agent/vault`：Markdown 库的解析、索引、监听、写笔记
- `agent/life`：闪念、开销、RSS / Release 速递
- `agent/vector`：sqlite-vec 或 BLOB 余弦

## 3. 对外接口

工具和频道调用这些包的函数，例如 `get_knowledge_store`、`get_schedule_store`、`search_vault`。没有统一的领域门面。控制台 CRUD 直接调其中一部分，见 [admin.md](./admin.md)。

## 4. 运行流程

模型通过 QQ 工具进入领域函数。催办到点由根上的 `agent/scheduler.py` 触发，不经过模型。速递由 `life/monitor.py` 的 cron 任务发送。Vault 监听在进程内增量索引。

## 5. 数据与副作用

都在 `agent/.runtime/qq/` 下，除了 Vault 正文在 `QQ_VAULT_PATH`。记忆、催办、文件索引、Vault 索引、向量是各自分开的库或目录。任务图 JSON 属于 Coding，在 `agent/tasks`，不要和催办 SQLite 混用。

## 6. 并发与恢复

知识库和催办存储用线程锁。文件索引也有锁。没有和 Harness Run 绑定的事务：工具可能已经写入领域数据，而 intent 仍是 UNKNOWN。这是账本要表达的「不确定有没有做成」，不是领域包自己的恢复协议。

## 7. 配置

路径和开关在 `agent/config.py`：`QQ_RUNTIME`、`FILES_DIR`、`MEMORY_DIR`、`SCHEDULES_DB`、`QQ_VECTOR_BACKEND`、`QQ_VAULT_PATH`、`QQ_VAULT_WATCH`、`QQ_VAULT_GIT_COMMIT`、`QQ_VAULT_GIT_PUSH`。速递时刻来自 `QQ_DIGEST_HOUR` / `QQ_DIGEST_MINUTE`（`life/monitor.py` 读取，缺省 8:30）。`QQ_DIGEST_USE_LLM` 为 `1` / `true` / `yes` 时才调模型压缩速递。

## 8. 测试

冒烟覆盖记忆、文件沙箱和催办的一部分。领域包没有单独的 `tests/domains`。架构测试禁止它们 import 发送客户端，除了速递那一处。

## 9. 已知限制

- `files/pipeline.py` 引用群缓存和 `wrap_untrusted`。`files/delivery.py` 引用近期文件缓存。`knowledge` 与 `vault/writer.py` 在部分路径上引用 `wrap_untrusted`。这些不是发送。
- `life/monitor.py` 会 `safe_send_msg`。这是登记过的例外。
- 根上的 `scheduler.py` 也会发送。它不在领域包名单里。

## 10. 维护规则

- 不要把这些包移进新的 `domains/` 目录。
- 不要在领域包里新增对 `agent.channel.send`、OneBot 或 `client_ref` 的 import。速递若要改发送方式，先改架构测试里的例外说明。
- 跨用户读写保持现有隔离：群记忆和私聊记忆的键不同。
