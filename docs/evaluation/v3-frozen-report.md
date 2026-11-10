# StateBench v3 正式测试

开跑前已经写好三件事：开发者复核、验证集选择、文件哈希。哈希在 `evals/statebench/v3/frozen_config.json`。`protocol.yaml` 在开跑前冻结，开跑之后没有改。开封标记在 `frozen_manifest.json`，`test_opened` 为 true。复核是 `developer_reviewed`，`third_party` 为 no。

验证集规则选中的是 react@1。测试集没有因此删掉任何一组，仍然是 48 条任务 × 3 种策略 × 2 次，共 288 次，全部完成。模型 `deepseek-flash`，温度 0。预算 16 轮、12 次观察、2 次重规划。没有在看到测试结果后重跑失败题。

| 策略 | 成功 | 过期写入 | 安全停止 | 部分完成 | 观察 | 提示 token | 补全 token | 每次成功 token | 耗时合计 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| react@1 | 80/96 | 1 | 12 | 1 | 279 | 339233 | 71273 | 5131.3 | 586.5 秒 |
| egaa@2 | 58/96 | 4 | 10 | 16 | 256 | 31200 | 15334 | 802.3 | 99.7 秒 |
| Always Refresh | 42/96 | 14 | 10 | 26 | 208 | 31200 | 15210 | 1105.0 | 98.0 秒 |

耗时是 96 次 `elapsed_ms` 相加，不是平均，也不是 P50 或 P95。

主对照是 EGAA 减 Always Refresh。成功率差的 95% 区间不含 0，EGAA 更高。观察差的区间也不含 0，EGAA 观察更多。单次 token 差的区间含 0。每次成功 token 更低，是因为成功数更多，不是因为每条轨迹更短。提示 token 两边都是 31200。

第二对照是 EGAA 减 ReAct。成功率差的区间不含 0，上界是 -5.2 个百分点。这份 24 个蓝图的样本不支持“EGAA 不差过 5 个百分点”。token 差的区间整个在 0 以下，EGAA 更少。

原始行和区间在 `evals/statebench/v3/results/test.json`。统计说明在 [v3-statistical-analysis.md](v3-statistical-analysis.md)。
