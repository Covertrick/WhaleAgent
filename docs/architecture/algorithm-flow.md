# 决策闭环

项目资料任务的调用顺序：

```text
公开目标
  → 选定并冻结 egaa@2
  → agent.engine
  → EGAAPolicy.next_step
       模型计划与原文抽取，然后 decide
       CONTINUE | OBSERVE | REPLAN | RECOVER | STOP
  → HarnessExecutorAdapter.execute
  → 观察或效果回执
  → apply_observation
  → 回到同一个 Policy
```

计划节点仍使用 `read_fact` / `write_fact`。应用层把它们翻译成 `search_vault`、`write_vault_draft`、`schedule_reminder` 和 `schedule_list`。算法包看不到这些工具名。

可重写的草稿不因为「下一步要写」而重读。创建提醒是不可逆节点，写之前会再取一次截止时间。截止时间的可见变化只重读这条证据；已经写完的草稿保持完成。

`v` 加整数可以直接比较。SHA-256 不能排序。应用层的修订账只在带来源和内容哈希时登记：同一来源、同一哈希保持原修订，内容变化才得到下一个修订。两个来源的值不一致时，当前证据改为 `UNKNOWN`，不可逆写入停止。没有来源标识的文本仍然不能支撑提醒。算法包本身不把哈希当成版本号。

账本把某次写入收成 `UNKNOWN` 时，这一轮停止。提醒场景会再查一次已有提醒，然后请求确认。同一次 Run 里不会把 `schedule_reminder` 再执行一遍。

## 策略开关

`agent/algorithms/policies.py` 的开关没有改：

| 名字 | use_validator | observe | repair |
|------|---------------|---------|--------|
| B0 | 否 | none | free |
| B1 | 是 | missing | regenerate |
| B2 | 是 | risk | local |
| B3 | 是 | always | local |
| B4 | 是 | risk | full_on_notice |

线上项目资料任务使用 B2，风险规则是 `before_irreversible`。StateBench 里的脚本 B0 仍是 `evals/statebench/b0.py`，不调用 `decide`。

## 原因码

`decide` 的原因码保持原样，测试锁定这些字符串：

`PLAN_INVALID`、`PLAN_CYCLE`、`UNVERIFIED`、`ANY_NOTICE`、`UNKNOWN_SCOPE`、`FACT_CHANGED`、`GOAL_MET`、`GOAL_UNVERIFIED`、`BLOCKED_NODES`、`NO_PENDING`、`REACT_BASELINE`、`OBSERVED_INVALIDATION`、`MISSING_EVIDENCE`、`ALWAYS_REFRESH`、`POTENTIALLY_STALE`、`PRECONDITIONS_HOLD`，以及 `OBSERVE_BUDGET`、`REPLAN_BUDGET`。

修复结果码（`PARAMETER_REBIND`、`STRUCTURE_REPLACED` 等）不是 `Decision.kind`。当前工作流的局部修复是重新绑定仍有效的证据值。没有单独重建子图时，不把它写成结构性规划优化。

## 目标核对

`application/goal_verifier.py` 只看当前 `VALID` 证据和状态为 `CONFIRMED` 的回执。StateBench 的评分仍在离线循环结束后进行，应用层不调用它。
