# 依赖规则

规则以 `tests/architecture/test_boundaries.py` 为准。下面是人话版本。

1. `agent/algorithms` 只依赖自身和标准库。禁止 channel、OneBot、statebench、harness、sqlite3。
2. `agent/harness` 不 import `agent.channel`，也不 import OneBot 客户端。会话键是普通字符串 `channel:user:group`。
3. `knowledge`、`files`、`vault`、`schedules`、`life` 不 import `agent.channel.send`、`agent.channel.onebot`、`agent.channel.client_ref`。例外只有 `agent/life/monitor.py` 的定时速递，它调用 `safe_send_msg`。
4. `agent/channel` 不 import `agent.algorithms`。它可以 import `agent.application`。`agent/application` 不 import channel、OneBot 或 StateBench。
5. QQ 静态工具名、`_fn` 的 schema 名、handlers 字典键、`QQ_SKILL_MANIFESTS` 四者相同，且与 `FORBIDDEN_ON_QQ` 不相交。
6. 根上的 `scheduler.py` 可以发 QQ。它是基础设施，不是上面的领域包。
7. 新增执行路径时注入 `ToolExecutor`，不要在 `core/loop.py` 里按工具名分支。
8. 不要为了目录变少把 `knowledge`、`files`、`vault`、`schedules`、`life`、`vector` 挪进 `agent/domains/`。

扫描命令：

```text
python -m unittest tests.architecture -v
```
