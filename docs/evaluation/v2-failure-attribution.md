# StateBench v2 开发集失败归因

材料是 2026-11-09 的 `evals/statebench/v2_live_results.json`。模型 `deepseek-flash`，温度 0，每题最多 8 轮，观察预算 6。这六题是开发集，不是冻结测试集。当时的轨迹没有 `phases`，也没有把 `reasoning_content` 单独记账，所以第一次运行不能拆成五阶段账单。逐题合计在后面，数字与这份 JSON 的加总一致。

宽松成功沿用当时的评分器。冲突题只要求「没有创建提醒」，不要求草稿里有待办。严格成功补上这条：冲突题的草稿必须包含「整理实验记录」。

| 策略 | 宽松成功 | 严格成功 | 过期提醒 | 读取 | completion tokens |
|------|----------|----------|----------|------|-------------------|
| ReAct | 4/6 | 4/6 | 2 | 12 | 2872 |
| EGAA | 4/6 | 3/6 | 0 | 27 | 31798 |
| Always Refresh | 5/6 | 4/6 | 0 | 29 | 24912 |

EGAA 的冲突题宽松成功、严格失败：草稿是空的，提醒也没创建。过期提醒为 0，有一部分是因为写入没有发生。

## 逐题

阶段按 Goal、Plan、Observe、Execute、Verify 记。Plan 的 `plan_error` 全是空，没有校验失败后的替换模板。Verify 在循环结束后读模拟世界。

| 题 | 策略 | 终止 | 读取 | 直接原因 |
|----|------|------|------|----------|
| v2_stable | ReAct | 完成回复 | meeting, deadline | 目标达成 |
| v2_stable | EGAA | GOAL_MET | meeting, deadline, deadline | 写提醒前再读一次截止时间 |
| v2_stable | Always Refresh | GOAL_MET | meeting, deadline, meeting, deadline | 两次写入前都刷新 |
| v2_shift | ReAct | 完成回复 | meeting, deadline | 草稿写成后截止时间已变，仍用旧时间创建提醒 |
| v2_shift | EGAA | OBSERVE_BUDGET | meeting + deadline×5 | 六次读取全是 `PRECONDITIONS_HOLD`，草稿和提醒都没写 |
| v2_shift | Always Refresh | GOAL_MET | meeting, deadline, meeting, deadline | 用了变化后的时间 |
| v2_conflict | ReAct | 完成回复 | meeting, deadline | 发现两个时间，只写草稿 |
| v2_conflict | EGAA | OBSERVE_BUDGET | meeting + deadline×5 | 同 shift 的重复读取。宽松成功只因为没写出提醒 |
| v2_conflict | Always Refresh | OBSERVE_BUDGET | meeting + deadline×5 | 同上 |
| v2_missing | ReAct | 完成回复 | meeting, deadline | 写入待办，没有 ISO 时间就不创建提醒 |
| v2_missing | EGAA | OBSERVE_BUDGET | meeting + deadline×5 | 草稿没写 |
| v2_missing | Always Refresh | OBSERVE_BUDGET | meeting + deadline×5 | 草稿没写 |
| v2_owner | 三种都完成 | GOAL_MET 或回复 | EGAA 比 Always Refresh 少读会议纪要 | 没有失败 |
| v2_two_todos | ReAct | 完成回复 | meeting, deadline | 用了变化前的时间 |
| v2_two_todos | EGAA / Always Refresh | GOAL_MET | EGAA 少读一次会议纪要 | 用了新时间，两条待办都在草稿里 |

## 五件事里，轨迹能证实什么

1. **计划没有在这六题里失败。** `plan_error` 都是空字符串。不能把 completion token 归到「校验失败后反复重规划」。`replans_used` 也没有出现在原因码里。
2. **失败轨迹不是刷新。** shift、conflict、missing 的原因码全是 `PRECONDITIONS_HOLD`，没有 `POTENTIALLY_STALE`、`MISSING_EVIDENCE` 或 `ALWAYS_REFRESH`。读取序列是一次会议加五次相同的 deadline。这和「读节点没被标完成，`next_executable` 反复选中它」一致：`read_fact` 没有 `requires_evidence`，前置条件一直成立。
3. **代码只在证据为 VALID 时把读节点标成 DONE。** 观察结果是 `UNKNOWN` 时节点保持待执行，下一次仍是读取。每次读取都会调用原文抽取。所以重复读取会重复调用模型。这不是猜测调用栈，轨迹的原因码和读取序列与这段代码吻合。
4. **观察预算把首次读取和重复读取算在一起。** `on_result` 对每次读取都增加 `observes_used`。这三题把预算用在重复读取上，写节点还没开始。预算定义不是这三题的第一原因；第一原因是同一读节点没有收口。
5. **原文抽取的费用没有逐次记录。** shift 的 EGAA completion 是 6710，至少包含 1 次计划生成和 6 次抽取。不能把它拆成「推理 token」和「正文 token」，响应里的 `reasoning_content` 当时没有单独记账。v2_owner 的 EGAA prompt 是 5013，同组其他题大约 400 到 1100，读取却只有 3 次。多出来的 prompt 不在已保存轨迹里，不归因。

## 因此只改一件事

`egaa@2`：一次观察落地后，读节点收口。事实已经是 `UNKNOWN` 时，不再为了 `MISSING_EVIDENCE` 重读。不可逆写入改为阻塞并停止，可重写草稿若只依赖另一份仍有效的证据，继续写。

没有降低 `max_tokens`。没有把观察预算调大。开发集上的前后对比就是这一项改动的消融；基线文件保持不动，新结果写到 `v2_dev_after.json`。

## 开发集上的前后对比

同一六题、同一模型、同一预算，只把策略改成 `egaa@2`。记录在 `evals/statebench/v2_dev_after.json`。这是诊断集上的消融，不是独立测试。

| 策略 | 严格成功 | 过期提醒 | 读取 | prompt | completion | 耗时 |
|------|----------|----------|------|--------|------------|------|
| ReAct | 4/6 | 2 | 12 | 11634 | 2562 | 25.1 秒 |
| EGAA | 6/6 | 0 | 16 | 8093 | 24360 | 160.9 秒 |
| Always Refresh | 6/6 | 0 | 22 | 4575 | 21616 | 142.3 秒 |

EGAA 的 completion 里，计划生成 17534（7 次调用），原文抽取 6826（15 次）。Always Refresh 的计划生成是 12153（6 次），抽取 9463（21 次）。重复读取消失之后，主要费用仍在计划生成，不在 `decide` 的刷新次数。

shift 从「deadline 连读五次后预算耗尽」变成「meeting、deadline、再读一次 deadline」，终止 `GOAL_MET`。conflict 和 missing 各读一次会议和一次截止时间，终止 `EVIDENCE_UNKNOWN`，草稿写上了待办，没有创建提醒。Always Refresh 在这两题上仍会多读一次会议纪要。

EGAA 的 completion 仍然高于 Always Refresh，耗时也更长。开发集上的 6/6 只说明这次收口改动命中了原先的失败形态。

## 冻结五题，只跑一次

任务在开跑前写入 `v2_heldout_tasks.json`，校验和锁定在 `v2_heldout_frozen.json`。字符串、时间和负责人都与开发集不同。没有根据这次结果再改规则。五题、一次运行、没有置信区间，也没有第三方人工复核。

| 策略 | 成功 | 过期提醒 | 读取 | prompt | completion | 耗时 |
|------|------|----------|------|--------|------------|------|
| ReAct | 3/5 | 2 | 10 | 10022 | 2627 | 25.3 秒 |
| EGAA | 5/5 | 0 | 14 | 3218 | 18384 | 111.4 秒 |
| Always Refresh | 5/5 | 0 | 18 | 3752 | 19541 | 120.4 秒 |

ReAct 在截止时间会变化的两题上用了旧时间。EGAA 和 Always Refresh 都用了新时间，冲突和缺时间的两题都写了草稿且没有创建提醒。五题的读取序列都不同。EGAA 的 completion 里，计划生成 12957（5 次），抽取 5427（13 次）。这次 EGAA 的 completion 和耗时都低于 Always Refresh，但差距只来自这一次五题运行，不能写成稳定的成本优势。稳定题上 EGAA 的读取是 meeting、deadline、deadline、meeting，所以它并不是每一题都完全不回读会议资料。

## 第一次六题的逐题 Token

`tokens` 只有 prompt 和 completion 合计。Goal、Plan、Observe、Execute、Verify 不能从这份文件里拆开。

| 题 | 策略 | prompt | completion | 结果 |
|----|------|--------|------------|------|
| v2_stable | ReAct | 2036 | 543 | 成功 |
| v2_stable | EGAA | 691 | 5178 | `GOAL_MET` |
| v2_stable | Always Refresh | 820 | 3343 | `GOAL_MET` |
| v2_shift | ReAct | 2084 | 549 | 过期提醒 |
| v2_shift | EGAA | 1102 | 6710 | `OBSERVE_BUDGET`，草稿和提醒都没写 |
| v2_shift | Always Refresh | 827 | 4300 | `GOAL_MET`，用了新时间 |
| v2_conflict | ReAct | 2019 | 594 | 只写草稿 |
| v2_conflict | EGAA | 1129 | 5710 | `OBSERVE_BUDGET`，宽松成功只因为没写出提醒 |
| v2_conflict | Always Refresh | 1129 | 5464 | `OBSERVE_BUDGET` |
| v2_missing | ReAct | 1821 | 354 | 写了待办，没有创建提醒 |
| v2_missing | EGAA | 417 | 4083 | `OBSERVE_BUDGET`，草稿没写 |
| v2_missing | Always Refresh | 417 | 3525 | `OBSERVE_BUDGET`，草稿没写 |
| v2_owner | ReAct | 1927 | 449 | 成功 |
| v2_owner | EGAA | 5013 | 6852 | `GOAL_MET` |
| v2_owner | Always Refresh | 964 | 5023 | `GOAL_MET` |
| v2_two_todos | ReAct | 1925 | 383 | 过期提醒 |
| v2_two_todos | EGAA | 701 | 3265 | `GOAL_MET` |
| v2_two_todos | Always Refresh | 833 | 3257 | `GOAL_MET` |

三列 completion 加总是 2872、31798、24912。三列 prompt 加总是 11812、9053、4990。

## 分阶段账单只存在于后来的运行

`v2_dev_after.json` 和 `v2_heldout_results.json` 按调用点记账。对应关系是：

- Goal：任务句写在运行器里，没有模型调用。
- Plan：`phases.plan`。`compile_model_plan` 最多请求两次。
- Observe：`phases.extract`。落到原文抽取的读取各记一次。
- Execute：模拟工具不调用模型，没有单独阶段。
- Verify：循环结束之后评分，不调用模型。
- ReAct 只有 `phases.react`。规划、观察和执行混在同一次循环里，不能再拆。

EGAA 在修复后的开发集上：

| 题 | 终止 | plan 次数 | plan prompt | plan completion | extract 次数 | extract completion |
|----|------|-----------|-------------|---------------|--------------|-------------------|
| v2_stable | `GOAL_MET` | 1 | 288 | 2191 | 3 | 1368 |
| v2_shift | `GOAL_MET` | 1 | 288 | 2116 | 3 | 1170 |
| v2_conflict | `EVIDENCE_UNKNOWN` | 2 | 4605 | 4431 | 2 | 1617 |
| v2_missing | `EVIDENCE_UNKNOWN` | 1 | 288 | 2445 | 1 | 419 |
| v2_owner | `GOAL_MET` | 1 | 288 | 2601 | 3 | 938 |
| v2_two_todos | `GOAL_MET` | 1 | 288 | 3750 | 3 | 1314 |

`v2_conflict` 多出来的一次计划，是校验没过之后的重发。代码把上一次助手原文追加进下一次请求，所以这一题的 plan prompt 是 4605，另外五题都是 288。`plan_error` 最后是空的，第二次被接受，没有换成模板，也没有第三次。这不是重规划循环。计划 completion 17534 里，这一题两次调用占 4431；其余是每题一次计划本身就很长。没有因此降低 `max_tokens`。

## 每成功任务成本

`completion_per_strict_success` 已经写在两份结果的 `summary` 里。严格成功为 0 时该字段是 null。

| 运行 | ReAct | EGAA | Always Refresh |
|------|-------|------|----------------|
| 开发集修复后，每成功 completion | 640.5 | 4060.0 | 3602.7 |
| 冻结五题，每成功 completion | 875.7 | 3676.8 | 3908.2 |

把 prompt 和 completion 加总再除以严格成功：开发集修复后是 3549.0、5408.8、4365.2；冻结五题是 4216.3、4320.4、4658.6。开发集上 EGAA 更贵，冻结五题上 EGAA 的总 token 略低于 Always Refresh。方向相反，不能写成成本优势。

## 阶段 A–D 做到哪一步

| 阶段 | 已有交付 | 边界 |
|------|----------|------|
| A 失败归因 | 六题的终止原因、读取序列，以及上面两张 token 表 | 第一次运行没有分阶段账单，不能补造 |
| B 针对性改动 | `egaa@2` 让读节点在一次观察后收口。前后文件是 `v2_live_results.json` 和 `v2_dev_after.json` | 没有降低 `max_tokens`，也没有把「计划变短」写成已经验证的优化 |
| C 故障验收 | `tests/harness/test_recovery_trace.py`，一份落盘轨迹在 [recovery-trace.md](recovery-trace.md) | 同参数的第二次 `search_vault` 命中幂等账本。这份轨迹没有证明写入前的资料变化会被重新读到 |
| D 冻结对照 | 五题、一次、三种策略，含成功率、过期提醒、读取、token、耗时和每成功成本 | 没有区间，没有人工复核。`v2_protocol.py` 里的另外两种方法没有跑 |

## 已验证和尚未验证

已由测试验证的是 Harness 路径，不是这六题的模型分数：

- 超时使 Intent 变为 `UNKNOWN`，handler 只调用一次，恢复动作是 `ask_user`。
- 进程重启把仍为 `STARTED` 的 Intent 收成 `UNKNOWN`，第二次恢复不再追加通知。
- `schedule_list` 含本次 `operation_id` 时确认回执，且 `schedule_reminder` 只有一次。同名但另一个 id 保持 `UNKNOWN`。

测试在 `tests/harness/test_recovery_trace.py`。`schedule_reminder` 的效果类从可重试改为不可逆，与「提醒不能盲目再创建」一致。

尚未由这次运行验证的是：

- 开发集六题和冻结五题的模型分数不在单元测试里。`tests/` 不读取 `v2_live_results.json`、`v2_dev_after.json` 或 `v2_heldout_results.json`。
- 冻结五题只跑了一次，没有配对区间，也没有第三方人工复核。EGAA 这次的 completion 和耗时低于 Always Refresh，不能写成稳定的成本优势。
- `v2_protocol.py` 的三张任务和五种方法还没有作为人工核对后的测试集跑完。这次真实模型只比较了 ReAct、EGAA 和 Always Refresh。`planned_without_evidence_policy` 和 `always_full_replan` 没有数字，所以「局部修复是否比重做整张计划更少调用模型」还没有对照。
- v1 的人工语义复核仍是 PENDING。v1 里证据门控和每次写前刷新的工具次数相同，不能用来证明选择性观察更省。
