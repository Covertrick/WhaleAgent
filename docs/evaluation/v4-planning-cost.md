# 规划成本：已经能拆开的部分

冻结五题里，EGAA 的 completion 是 18384，其中计划生成 12957，约占 70.5%。开发集修复后的计划生成是 17534 / 24360。这两次的分阶段数字来自当时的 `phases.plan` 和 `phases.extract`，不是新跑的一轮。

现在每次模型响应可以记成一条 `ModelCallUsage`：阶段、prompt、completion、cached。接口没有返回的字段保持空，不补成 0。阶段名固定为 `goal_parse`、`plan_generate`、`evidence_extract`、`plan_repair`、`react_step`、`result_summarize`。没有发生的阶段不计数。记账默认关闭，评测调用 `enable_phase_recording` 才留下记录。

下面三项还没有跑，所以没有前后对照，也不能写成规划成本已经下降：

| 版本 | 状态 |
|------|------|
| P0 当前 `egaa@2` | 已有开发集和冻结五题的计划 / 抽取合计 |
| P1 紧凑计划 | 没有改提示词，也没有新的模型运行 |
| P2 紧凑计划加局部更新 | 局部修复的代码还在，没有和全量重规划做真实模型费用对照 |

没有降低 `max_tokens`。受控 Plan Replay 和端到端成本也还没有分开测量。
