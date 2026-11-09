# ADR 0003：算法隔离

## 状态

部分取代。算法包不得 import channel、Harness、StateBench 和 sqlite，这一条仍然有效。不把 `decide` 接到 QQ Run 的决定由 [ADR 0004](./0004-application-driver.md) 取代：应用层可以在同一次 Run 上调用 `decide`。

## 背景

EGAA 要和 QQ 线上路径比较，但不能共享权限或隐藏世界。`decide` 已经返回 `OBSERVE`、`CONTINUE`、`REPLAN`、`RECOVER`、`STOP`。测试锁定这些字符串和原因码。

## 决定

- 不在 `run_qq_agent` 里直接 import `decide`。项目资料任务经 `agent.application` 调用它，见 ADR 0004。
- 不改 `controller.decide` 的分支、阈值和公开原因码。
- 不在 `agent/algorithms` 里新增一套平行的动作类型。现有 `Decision` 就是缝。
- 算法包禁止 import channel、OneBot、StateBench、Harness 和 sqlite。
- B1–B4 继续由 `evals/statebench` 持有真值并调用 `decide`。B0 继续用脚本化 `agent_loop`。

## 后果

普通 QQ 消息仍不调用 `decide`。项目资料任务经应用层调用它。评测数字只来自已归档的 StateBench 结果，除非单独重跑并更新冻结记录。开发集索引不能当成正式成功率。
