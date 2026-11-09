# StateBench v3 试验任务

正式的 48 个蓝图、96 条实例还没有写。测试集没有开放，预算也还是空的。预注册文本在 [evals/statebench/v3/protocol.yaml](../../evals/statebench/v3/protocol.yaml)。

现在落盘的是 12 个决策结构不同的试验蓝图，每个两条文本变体，共 24 条。它们覆盖 S0 到 S5，以及并行、扇出、长链、多来源汇合四种依赖图。变体改的是体裁和句子，不是只换一个时间。可见提示里没有期望行为和隐藏事件。

核对人是开发者本人，不是第三方。24 行核对记录由 `audit_rows()` 生成，`third_party` 都是 `no`。

```bash
python -m unittest tests.statebench.test_v3_trial -v
```
