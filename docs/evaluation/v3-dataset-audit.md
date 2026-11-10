# StateBench v3 数据集

48 个蓝图，每个两条正文变体，共 96 条。划分是开发 12、验证 12、测试 24 个蓝图。S0 到 S5 各 8 个蓝图，每个场景都包含并行、扇出、长链和汇合。

公开提示只写要读的资料名和决策约束。变化后的原句、新时间和新负责人不出现在提示里。评分在轨迹结束后看隐藏世界。

自动审计 96 行都没有失败备注。开发者逐条看过目标、工具、安全停止、事件、评分器、泄漏、变体和划分。`reviewer_audit.csv` 记的是 `developer_reviewed`，`third_party` 为 no。这不是第三方盲审，也不是人工 PASS。

复核时改了三处，都在任何正式模型运行之前：

- `s0_join_agree` 的公开目标写成两份时间必须一致，数据里只有一份时间。目标已改成按日程原文创建提醒。
- `s5_fanout_partial` 原来和验证集 `s1_fanout_time` 是同一份原文。已换成不同正文，并禁止待办草稿写入新时间。
- `s5_join_abstain_keep_draft` 原来和开发集 `s3_join_hidden` 是同一份原文。已换成不同时间和待办。

无关资料的旧词和新词都会让草稿失败。同一份资料只禁止被换掉的新值。需要把两份原文合成一段草稿的链任务没有放宽：EGAA 的 `value_from` 仍然只能指向一份事实。

```bash
python -m evals.statebench.v3.audit
python -m unittest tests.statebench.test_v3_dataset -v
```

产物：`evals/statebench/v3/splits.json`、`reviewer_audit.csv`、`fixtures/public/`、`fixtures/private/`。v1、v2 的结果文件哈希没有改。
