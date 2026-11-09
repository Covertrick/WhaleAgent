# 规划消融

P0 仍是 `egaa@2`。冻结五题里计划生成占 EGAA completion 的 12957 / 18384。这是旧结果，不是新一轮。

P1 只在 `compile_model_plan(..., compact=True)` 里收紧 JSON 字段。没有降低 `max_tokens`。没有对开发集跑 P0、P1、P2 的真实模型对照，所以没有计划 token 下降的数字。

P2 的 `local_or_full_update` 会先改未完成节点，局部结果不合法才整图重编译。单测确认已完成节点保持 DONE。这不是端到端费用对照。
