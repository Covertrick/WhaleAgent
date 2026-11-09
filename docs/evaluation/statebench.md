# StateBench

StateBench 是可重置的离线任务环境，用来比较脚本化 ReAct（B0）和证据门控策略（B1–B4）。它不连接 NapCat，也不把隐藏状态交给 `agent.algorithms`。

## 任务

- 任务与划分：`evals/statebench/scenarios/tasks.json`、`splits.json`
- 种子场景：`evals/statebench/scenarios/seed/`
- 计划里的规模是开发 24、验证 16、冻结测试 40。开发集索引 `dev_run_index.md` 按策略各完成 24 条。冻结测试报告 `d14_report.md` 写的是 40 条。验证集任务 id 列在 `frozen_config.json` 的 `logged_task_ids`。
- 题是受控模板实例。`audit.md` 写明不能把题数说成 80 种或 40 种独立任务类型，并列出结构重复的蓝图。

## 环境

`evals/statebench/environment.py`：SQLite 是权威状态，`files/` 是可重建镜像。测试用独立临时目录。

`HiddenEvent` 有 `checkpoint`、`fact_key`、`value`、`version`、`notify`。`apply_checkpoint` 写入真值，只把 `notify` 的事实键返回给 Agent。

工具白名单在 `experiment.yaml`：`read_fact`、`write_fact`、`list_facts`。预算：最多 8 次工具调用，观察 3，重规划 2。`budget_semantics` 写明检查发生在执行前，以及哪些步骤计入观察、工具和决策。

## Mock 与 Live

**Mock 是默认。**

`b0.resolve_llm`：参数显式给 `mock` 或 `live` 时用参数；否则只有环境变量 `STATEBENCH_LLM=live` 才走 live，别的情况都是 mock。`experiment.yaml` 的 `default_llm` 也是 `mock`，`live_env` 是 `STATEBENCH_LLM`。

`python -m evals.statebench.b0 --task ...` 可用 `--mock` 或 `--live`。两个都写会退出 2。都不写时交给 `resolve_llm(None)`，因此仍看 `STATEBENCH_LLM`。

`python -m evals.statebench.runner --split {dev,val,test}` **必须**带 `--mock`。不带就退出 2，提示 Live 对照另开，不混入这张表。runner 里 B0 调用 `run_b0(..., llm="mock")`，不会因为环境变量改成 live。

B1–B4 的 `run_controlled` 不请求模型。它调用 `decide` 和模拟工具。

Live 会请求 `agent.core.llm` 和 `config.MODEL_NAME`。这次重构没有跑 Live，也没有改冻结结果。

## 隐藏真值

评分在 `scorer.py`。目标是否达成看环境真值，不看模型自述。`stale_uses` 比较执行时用到的版本和当时真值版本。没有失效判定日志时，`false_invalidation_metric` 返回 `not_applicable`，不把「没调用」记成 0。

`audit.py` 的 `HIDDEN_FIELDS` 包括 `events`、`hidden_events`、`success`、`constraints`、`expected`、`actual_source_version_at_write`。这些不该出现在交给决策器的公开载荷里。

## 评分与冻结

冻结清单：`frozen_manifest.json`（schema `statebench-v1`，以及 tasks / splits / fixtures / scoring / checkpoint 的 sha256）。冻结规则：`frozen_config.json`，`risk_mode` 为 `before_irreversible`，观察预算 3，重规划预算 2，`human_review` 为 `PENDING`。

归档主表在 `d14_report.md` 和 `d14_table.json`。`audit.md` 的人工语义复核也是 `PENDING`。机器检查写的是 schema、重置与事件、评分器通过。

本次没有重算这些文件。引用数字时以那些文件为准，不要把开发集索引写成正式成功率。`dev_run_index.md` 自己写了「这是原始轨迹索引，不是正式成功率」，并写明开发集上 B2 与 B3 的观察计数相同，不能单独把原因码差异写成成本优势。

## 冻结协议

不要改 `tasks.json`、`splits.json`、种子、`frozen_manifest.json`、`frozen_config.json`、评分函数的对外结果、`d14_report.md`、`d14_table.json`。验证集只使用已经写明的那一条风险规则。`experiment.yaml` 的 `risk.selection` 说明了平局时怎么选，以及主预算下至少 4 条因预算停止时改用观察预算 4 再选一次。`frozen_config.json` 的 `fallback_used` 是 false。

复现命令以 `d14_report.md` 文末为准，需要时才跑，并且会写 `dev_run_index.md` 或报告。日常边界检查用：

```text
python -m unittest tests.statebench.test_d1_d3 tests.statebench.test_d8_d15 -v
python -m evals.statebench.audit
```

`audit` 会重写 `audit.md`。若只想核对而不改工作区，先看 diff。
