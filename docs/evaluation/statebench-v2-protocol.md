# StateBench v2 协议

v1 的 40 道冻结题继续保留，位置和评分契约都不改。它们证明的是：在「读一次，再写一次」上，写前重读能避免过期写入。B2 和 B3 的工具次数相同，所以 v1 不能说明选择性观察更省。

2026-11-09 用 `python -m evals.statebench.v2_live` 跑过一次真实模型。模型是 `deepseek-flash`，题目是 `v2_live.py` 里的 6 道开发者任务，方法只有 ReAct、EGAA 和 Always Refresh。数字在根目录 README，轨迹在 `evals/statebench/v2_live_results.json`。那次运行里 EGAA 的成功率没有高于 Always Refresh。

下面仍是正式对照要遵守的条件。`v2_protocol.py` 里的三张任务描述和五种方法还没有作为人工核对后的测试集跑完。开发者这 6 题不能代替那一套。

## 双方看见的信息相同

`evals/statebench/v2_protocol.py` 的 `visible_task` 只保留 `task_id`、`prompt`、`branches`、`tool_schemas`。

模型循环和 EGAA 都从这份视图出发。`events`、`initial_facts`、`success`、`expected`、`source_key`、`target_key` 留在评分器。谁先看见这些字段，这次对照就作废。

当前三张任务只描述用户能看见的分支：

| 任务 | 要面对的选择 |
|------|----------------|
| `v2_conflict` | 两份资料的截止时间冲突时，哪一步可以继续，哪一步要停下来问 |
| `v2_partial_change` | 资料没变时不重写草稿；提醒必须使用新的截止时间 |
| `v2_unknown_effect` | 提醒没有确认回执时先查询，查不清就停止 |

## 对照

五种方法使用同一个模型、同一批可见任务、同一套工具参数和同一个总预算：

- 真实模型 ReAct
- 有计划、但没有动态证据策略
- EGAA 选择性观察
- 每次写前都刷新
- 任何通知都整计划重做

开发集用来调试，验证集用来选定事先写明的规则，测试集只打开一次。报告保存逐任务轨迹、分子分母、工具次数、token 和配对区间。温度设为 0 时仍要记录实际返回，并按预算允许的次数重复。

可以写进结果的差异只有两类：相近成功率下观察成本是否更低，以及局部修复是否比重做整张计划更少调用模型。如果仍然相同，就写成没有差异。

这条协议不要求接公开基准，也不要求训练模型。

## 已经跑过的记录

开发集六题的第一次真实模型结果在 `evals/statebench/v2_live_results.json`。归因和 `egaa@2` 的前后对比在 [v2-failure-attribution.md](v2-failure-attribution.md)。修复后的同一开发集在 `v2_dev_after.json`，它不能当作独立测试。

`v2_heldout_tasks.json` 在开跑前冻结，校验和在 `v2_heldout_frozen.json`。2026-11-10 用 `python -m evals.statebench.v2_live --split heldout` 跑了一次，只比较 ReAct、EGAA 和 Always Refresh。五题、一次运行、没有配对区间，也没有第三方人工复核。成功率、过期提醒、读取、token、耗时和 `completion_per_strict_success` 都在 `v2_heldout_results.json` 的 `summary` 里，摘录在根目录 README。这五题不能再拿来调参。
