# 复现

StateBench 的冻结材料已经在仓库里。复现是重跑检查，不是改写冻结文件。

## 不需要模型的检查

```text
python -m unittest tests.algorithm.test_invariants tests.algorithm.test_d4_d7 tests.algorithm.test_d4_d7_flow tests.algorithm.test_d8_repair tests.algorithm.test_d9_policy -v
python -m unittest tests.statebench.test_d1_d3 tests.statebench.test_d8_d15 -v
python -m unittest tests.architecture tests.harness -v
python -m evals.statebench.audit
```

`audit` 会把结果写回 `evals/statebench/audit.md`。人工复核行应保持 PENDING。若工作区因此出现无关 diff，不要把它当成新的实验结论。

## 报告里写的对照命令

`d14_report.md` 文末是：

```text
python -m evals.statebench.runner --split dev --mock
python -m evals.statebench.freeze_config --mock
python -m evals.statebench.report --mock
```

`runner --split dev` 会重写 `dev_run_index.md`。`report` 会重写报告。这次重构没有执行这三条。要核对归档数字，直接读 `d14_report.md`、`d14_table.json`、`frozen_config.json`、`frozen_manifest.json`。

`runner` 不接受不带 `--mock` 的调用。Live 只在 `python -m evals.statebench.b0 --live` 或 `STATEBENCH_LLM=live` 且调用 `run_b0` 时没有显式 `llm="mock"` 的情况下发生。正式 runner 对 B0 写死了 `llm="mock"`。

## 哈希

`frozen_manifest.json` 记录 tasks、splits、fixtures、scoring contract、checkpoint contract 的 sha256，以及 `generator_seed` `20261109`。不要在文档里手算一套新哈希来替换它。

## Coding A–F

在线部分需要模型和密钥。离线部分是 `evals/` 里的断言。汇总已在 `evals/SUMMARY.md`。不要为了刷新汇总去打在线 API。

## 冒烟

```text
python -m agent.smoke_test
```

它不连 NapCat。若失败原因是缺可选依赖或要下载嵌入模型，记下环境原因，不要放宽断言，也不要为此联网。
