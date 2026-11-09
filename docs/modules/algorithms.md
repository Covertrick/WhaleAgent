# Algorithms

## 1. 定位

`agent/algorithms` 是 EGAA 的决策规则。它根据信念、计划节点和调用方给的阈值，返回 `CONTINUE`、`OBSERVE`、`REPLAN`、`RECOVER` 或 `STOP`。

它不执行 QQ 工具，不写 Harness 账本，不读 StateBench 的隐藏事件，也不估计概率。阈值由 `DecideContext` 传入。

## 2. 代码位置

| 文件 | 职责 |
|------|------|
| `types.py` | 证据、计划节点、信念、目标、风险规则、`Decision` |
| `policies.py` | B0–B4 开关表 |
| `planner.py` | 公开任务视图、依赖环、下一可执行节点、参数解析 |
| `validator.py` | 前置条件 `VALID` / `INVALID` / `UNKNOWN` |
| `evidence.py` | 只按已发生的观察更新信念 |
| `invalidation.py` | 事实键如何影响后继节点 |
| `repair.py` | 局部修复时保留 `DONE` |
| `controller.py` | `decide` |

没有单独的 seam 模块。缝就是 `Decision`。说明见 [algorithm-flow.md](../architecture/algorithm-flow.md)。

## 3. 对外接口

`agent.algorithms` 导出：`decide`、`get_policy`、`POLICIES`、`BeliefState`、`Decision`、`DecideContext`、`Evidence`、`Goal`、`PlanNode`、`RiskRule`。

`decide(belief, nodes, ctx) -> Decision`。`Decision.kind` 只能是 `CONTINUE`、`OBSERVE`、`REPLAN`、`RECOVER`、`STOP`。

确认通知用 `acknowledge`。它不检查观察是否成功。调用方在槽位更新成功后才应该调用。`acknowledgement_allowed` 用来做这个判断。

## 4. 运行流程

`decide` 的顺序（没有改）：

1. 计划不合法 → `STOP`，原因码是 `plan_errors` 的 `error_code`（`PLAN_INVALID` 或 `PLAN_CYCLE`）。
2. 有未验证节点 → `RECOVER` / `UNVERIFIED`。
3. 策略 `full_on_notice` 且有未处理通知 → `REPLAN` / `ANY_NOTICE`，或预算用尽则 `STOP`。
4. 策略 `observe=risk` 时，按事实键与已用证据的关系给 `UNKNOWN_SCOPE` 或 `FACT_CHANGED`。
5. `goal_verified` → `STOP` / `GOAL_MET`。
6. 没有可执行节点：全完成但目标未验证 → `GOAL_UNVERIFIED`；有阻塞且策略不是 `free` → `BLOCKED_NODES`；否则 `NO_PENDING`。
7. 不用验证器 → `CONTINUE` / `REACT_BASELINE`。这是策略表里的 B0，不是 StateBench 的 `b0.py`。
8. 前置条件 `INVALID` → `REPLAN` / `OBSERVED_INVALIDATION`。`local` 只标受影响节点，否则标全部未完成节点。
9. `UNKNOWN` → `OBSERVE` / `MISSING_EVIDENCE`。
10. `observe=always` → `ALWAYS_REFRESH`。`observe=risk` 且证据过旧或下一步不可逆 → `POTENTIALLY_STALE`。
11. 否则 `CONTINUE` / `PRECONDITIONS_HOLD`。

观察或重规划超过 `observe_budget` / `replan_budget` 时变成 `STOP`，原因码 `OBSERVE_BUDGET` 或 `REPLAN_BUDGET`。

## 5. 数据与副作用

只有内存里的 dataclass。证据状态是 `VALID` / `INVALID` / `UNKNOWN` / `SUPERSEDED`。计划节点状态是 `PENDING` / `READY` / `DONE` / `BLOCKED`。

`Goal` 是信念侧可核对的检查。评分器另用世界真值，不读这段。包内注释写明没有 `WorldTruth`。

## 6. 并发与恢复

这些函数是同步的，没有锁，也没有崩溃恢复。未确认副作用属于 Harness，不属于这里。`RECOVER` 只表示调用方还有未验证节点，不会自己重试工具。

## 7. 配置

没有环境变量。策略名必须是 `B0`–`B4`，否则 `get_policy` 抛 `KeyError`。风险规则只有 `evidence_age` 和 `before_irreversible`。冻结测试选用哪一条，写在 `evals/statebench/frozen_config.json`，不写在这个包里。

## 8. 测试

```text
python -m unittest tests.algorithm.test_invariants tests.algorithm.test_d4_d7 tests.algorithm.test_d4_d7_flow tests.algorithm.test_d8_repair tests.algorithm.test_d9_policy -v
```

这些测试不调用模型。原因码和 `Decision.kind` 是公开字符串，不要改名。

边界：

```text
python -m unittest tests.architecture.test_boundaries.BoundaryTests.test_algorithms_do_not_import_channel_onebot_statebench_or_harness -v
```

## 9. 已知限制

- 包内 B0 策略和 StateBench 的 B0 脚本循环不是同一条路径。
- `decide` 不执行动作。B1–B4 的模拟执行在 `evals/statebench/execute.py`。
- 项目资料任务由 `agent/application` 在同一次 QQ Run 上调用 `decide`。其它 QQ 消息仍走模型循环。算法包自己不 import Harness。
- 修复结果码和决策原因码是两套字符串。

## 10. 维护规则

- 不要 import `agent.channel`、OneBot、`evals.statebench`、`agent.harness` 或 sqlite。
- 不要改阈值默认值或 `decide` 的分支来「修」评测数字。
- 新增原因码要同时改断言它的测试。不要给现有码改名。
- 隐藏状态进这个包就是边界破坏。
