# 系统总览

WhaleAgent 是一个状态感知的长任务 Agent。一次用户目标从 QQ 进入，Harness 打开唯一的 Run，应用层驱动决策，工具通过同一个执行器落到文件、Vault 和催办。

`agent/algorithms` 只返回 `decide` 的结果。`agent/application` 负责把这个结果交给执行器，并把回执收成观察。StateBench 提供可重置世界和评分，正式对照不经过 NapCat。

## 一次 Run 冻结一个 Policy

`start_run` 之后立刻选定策略，并把 `policy_name`、`policy_version` 写入这笔 Run。Engine 之后只调用这一个 Policy。

| 入口 | 冻结结果 | 执行 |
|------|----------|------|
| 整理或同步项目资料、会议、截止、提醒、待办、Vault | `egaa@2` | 同一个 `HarnessExecutorAdapter` |
| 其它 QQ 消息 | `react@1` | 同一个适配器 |
| Coding CLI | `react@1` | `CodingExecutorAdapter`，不写 QQ 账本 |
| StateBench v1 | 不进入这条 Run | 冻结 Runner。B0 是脚本，B1–B4 调用 `decide`，用来复现旧结果 |
| StateBench v2 | 与线上相同的 Policy 对象 | 同一个 Engine，外加模拟执行适配器。评分器在循环结束后读取世界 |
| StateBench v3 | 48 个蓝图、96 个实例的离线世界 | 公开提示与隐藏世界分开。人工复核未完成，测试集没有开封 |

## 谁做什么

| 组件 | 负责 | 不负责 |
|------|------|--------|
| `channel` | 收消息、去重、限流，打开 Run 后选定 Policy | 不 import `agent.algorithms`，不在每一步改策略 |
| `agent.engine` | 轮次、预算、工具执行和终止 | 不选择证据，不另写副作用账本 |
| `policies` | ReAct 的单次模型决策，或 EGAA 的计划、抽取和 `decide` | 不直接执行外部工具 |
| `algorithms.decide` | 继续、观察、修复、恢复或停止 | 不执行工具，不 import Harness |
| `HarnessExecutorAdapter` | 契约、Intent、沙箱、UNKNOWN | 不决定下一个规划动作 |
| StateBench v1 | 复现冻结结果 | 不连接线上会话，也不改用新 Engine |
| StateBench v2 | 在模拟世界里跑同一个 Engine | 评分器独立，不把隐藏真值交给策略 |
| StateBench v3 | 可重置的多分支世界和评分 | 不进入 QQ 业务代码。正式模型对照还没有跑 |

## 依赖

算法包仍然不能 import channel、Harness、StateBench 或 sqlite。应用层可以调用算法和 Harness，不能 import channel 或 StateBench。频道可以调用应用层。这些边界由 `tests/architecture` 扫描。

操作细节仍在 [architecture.md](../architecture.md)、[logic-flow.md](../logic-flow.md)、[files.md](../files.md)。和本页冲突时，以代码和本目录为准。
