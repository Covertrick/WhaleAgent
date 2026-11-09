# StateBench v3 数据集

48 个蓝图，每个两条正文变体，共 96 条。划分是开发 12、验证 12、测试 24 个蓝图。S0 到 S5 各 8 个蓝图，每个场景都包含并行、扇出、长链和汇合。

公开提示只写要读的资料名和决策约束。变化后的原句、新时间和新负责人不出现在提示里。评分在脚本化轨迹结束后看隐藏世界。

自动审计 96 行都没有失败备注。人工复核全部是 `HUMAN_REVIEW_PENDING`，不是第三方审核，也不是人工 PASS。因此测试集没有开封。

```bash
python -m evals.statebench.v3.audit
python -m unittest tests.statebench.test_v3_dataset -v
```

产物：`evals/statebench/v3/splits.json`、`reviewer_audit.csv`、`fixtures/public/`、`fixtures/private/`。原先 `blueprints.py` 里的 12 条试验提示还在，可执行数据集以 `catalog.py` 为准。v1、v2 的结果文件哈希没有改。
