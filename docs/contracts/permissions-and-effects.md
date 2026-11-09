# 权限与效果

两套权限，不合并。

## QQ 效果类

`agent/harness/effect.py`：

| 类 | UNKNOWN 时的恢复 | 含义 |
|----|------------------|------|
| `idempotent` | `RETRY` | 文案说可以重做。启动恢复仍要求用户再发一次 |
| `retryable` | `RETRY_SAME_KEY` | 按同一次请求补做，不另开一份。同样不在启动时自动执行 |
| `irreversible` | `ASK_USER` | 不自动再做。用户回「已经好了」或「再来一次」 |
| `requires_confirm` | `BACK_TO_CONFIRM` | 停在确认前，不擅自执行 |

未知的效果类字符串也落到 `ASK_USER`。

内置工具的类写在 `qq_skills.py`。例如 `web_search` 是幂等，`delete_memory` 和 `send_local_file` 是不可逆，`delete_file` 需要确认。改类会改变 UNKNOWN 文案，不属于这次重构。

guardrails 里若有「禁止自动重试」或「一律禁止重试」，`blocks_auto_retry` 对不可逆工具生效：同参数已经失败或未知时，`begin_intent` 不再执行。没有这两句时，下一次用户触发的调用仍可能再次执行。重构没有把「所有不可逆 UNKNOWN」改成无条件拒绝，因为那会改变现有语义。一次 `execute` 内部不会因为 UNKNOWN 再调 handler。

## QQ 权限字符串

`SkillManifest.permissions` 是声明，例如 `net.read`、`memory.write`、`file.send`。`begin_intent` 当前用契约是否存在、快照、幂等键和 guardrails 做决定，没有另一套按 permission 字符串匹配用户角色的引擎。不要在 schema 里再抄一份「是否需要确认」。

## Coding 权限

`hooks/permission.py`：

- bash 命中拒绝列表则直接错误
- 破坏性片段或越出 `WORKDIR` 时询问 stdin
- `mcp__` 且 policy 不是 `allow` 时询问

这只在工具真的被调用时发生。QQ handlers 里没有这些名字。`CodingExecutorAdapter` 仍会跑 `PreToolUse`，所以 CLI 的拒绝列表还在。

## 谁不能获得谁的权限

- QQ 适配器固定自己的 handlers，不接收循环换上的 Coding / MCP 池。
- Coding 适配器不写 QQ 账本，因此也不会套用 QQ 契约拒绝。它能跑的是 CLI 放进池子的工具。
- StateBench 工具只有 `experiment.yaml` 的 `tool_whitelist`：`read_fact`、`write_fact`、`list_facts`。B0 若 handlers 超出白名单会抛错。
