# 动作与观察

这里说的是 EGAA，不是 QQ 的 tool message。

## 已有类型

都在 `agent/algorithms/types.py`：

| 类型 | 作用 |
|------|------|
| `Goal` | 信念侧可核对的 `(fact, value)` 检查。评分不用它 |
| `PolicySpec` | 在 `policies.py`。验证器、观察时机、修复方式 |
| `Decision` | `kind` + 目标节点 + 原因码 + 证据 id + 阈值标签 |
| `BeliefState` | 证据表、观察历史、槽位 |
| `Evidence` | 一次观察的值和版本 |
| `PlanNode` | 动作名、参数、依赖、是否不可逆 |

`Decision.kind` 只有：`OBSERVE`、`CONTINUE`、`REPLAN`、`RECOVER`、`STOP`。

## 谁把决策变成动作

项目资料任务：Run 冻结 `egaa@2`。`EGAAPolicy` 调用 `decide`，Engine 经 `HarnessExecutorAdapter` 执行 `search_vault`、`write_vault_draft`、`schedule_reminder` 和 `schedule_list`。观察经 `apply_observation` 回到信念。目标核对只用已确认回执。真实模式下，草稿值来自原文抽取，抽取片段必须出现在工具文本里。

其它 QQ 消息：Run 冻结 `react@1`。`ReActPolicy` 只做一次模型推理，Engine 执行工具。这条路径不调用 `decide`。

StateBench v1 的 B1–B4：`evals/statebench/execute.py` 的 `run_controlled` 调用同一个 `decide`，再对模拟环境做 `read_fact` / `write_fact` / `list_facts`。这是冻结复现路径。

StateBench v1 的 B0：`evals/statebench/b0.py` 不调用 `decide`。脚本回复进 `agent_loop`，工具是同一环境上的模拟函数。

StateBench v2：同一个 Engine 和 Policy，执行器换成模拟适配器。评分器不进入 Engine 的可见状态。

## 观察里没有的东西

`Environment.apply_checkpoint` 的返回值只含 `notify` 为真的事实键。`env_only`、未通知的新值、`expected` 不进入算法包。评分在回合结束后用真值，模型声称完成不会改变 `scorer.py` 的结果。
