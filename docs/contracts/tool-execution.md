# 工具执行契约

## 静态契约

静态字段描述「这个工具是什么」，不描述「这一次谁可以跑」。

内置 QQ 工具的权威在 `agent/harness/qq_skills.py` 的 `QQ_SKILL_MANIFESTS`：

- 名字
- 版本（当前表是 `1.0.0`）
- `effect_class`
- `permissions`
- `sandbox_policy`（内置项都是 `none`）
- 给人看的短描述

参数 schema 和给模型看的长描述只在 `agent/tools/qq.py` 的 `_fn(...)`。handler 也在那里。没有第二份 `ToolSpec`。注册表没有把这两边合成一个新类型。

两边必须名字相同。`build_tools` 在返回前断言 schema、handlers、`QQ_TOOL_NAMES` 和契约表一致。`tests/architecture` 再查一次，并确认与 `FORBIDDEN_ON_QQ` 不相交。短描述和长描述允许不同，测试不要求文字相同。

插件是另一份来源：`plugins/*/manifest.yaml`，由 `SkillRegistry.scan` 索引。字段见 [plugins-and-skills.md](../modules/plugins-and-skills.md)。它不从 QQ 内置表生成，内置表也不读 yaml。

Coding 工具的 schema 在 `agent/tools/__init__.py` 和 `base.py`。它们没有 `SkillManifest`，也不进 QQ 契约表。

## 运行时决定

这些不写进工具 schema：

| 决定 | 在哪里 |
|------|--------|
| 这次 Run 是否要求契约 | `start_run(require_contract=True)` |
| 没有契约就拒绝 | `begin_intent` |
| 同参数幂等命中 | `begin_intent` |
| 不可逆且 guardrails 禁止自动重试 | `blocks_auto_retry` + `begin_intent` |
| 沙箱级别 | 快照里的 `sandbox_policy`，以及 `dispatch` 对 `untrusted` 的提升 |
| 结果算成功、失败还是未知 | `execute_tool` 看异常和返回文本 |
| Coding 的 bash / 路径 / MCP 询问 | `hooks/permission.py`，只对那些工具名生效 |
| 这次调用写不写 QQ 账本 | 有当前 Run，且没有 `use_ledger=False` |

## 执行口

```text
class ToolExecutor(Protocol):
    def execute(self, name: str, arguments: dict) -> dict: ...
```

返回值至少有 `content`。实现：

- `HarnessExecutorAdapter`：必须已有 Run，然后调用 `execute_tool`，顺序不变。
- `CodingExecutorAdapter`：`execute_tool(..., use_ledger=False)`。
- 不注入时：`loop` 直接 `execute_tool`。B0 走这条。

`tool_call_id` 通过适配器的 `bind_call` 传入，因为协议签名里没有它。后台 bash 需要这个 id。QQ 白名单没有 bash。

没有新增 `actions.py` 或 `context.py`。工具调用仍是循环里的 dict。QQ 的请求上下文仍是 `ChatContext`。算法侧的动作请求仍是 `Decision`，不是第三个平行类型。
