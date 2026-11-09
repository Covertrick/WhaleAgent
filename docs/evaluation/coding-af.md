# Coding A–F 历史结果

这是 Coding Harness 的工具评测，不是 EGAA，也不是 StateBench。原始汇总在仓库根的 `evals/SUMMARY.md`。下面只转述该文件，没有重跑。

- 模型：qwen3.7-plus（以当时的 `.env` 为准）
- 日期：2026-08-21
- 范围：A–F，离线加在线

| 模式 | 通过 | 失败 | Token |
|------|-----:|-----:|------:|
| Offline | 17 | 0 | 0 |
| Online | 31 | 0 | 约 330,924 |
| 合计有效题 | 48 | 0 | 约 330,924 |

分维度（离线 + 在线合计通过）：A 工具 12，B 权限 10，C 任务图 10，D 后台 6，E MCP 8，F 上下文 2。在线各维的分子以 `evals/SUMMARY.md` 为准。

`python -m evals.runner` 会在本地 `evals/reports/` 写 `report_*.md`。该目录默认不入库。`SUMMARY.md` 是可入库的副本。

文件末尾注明：部分用例结束时记忆提取报「任务目录不在工作区内」，不影响该次通过率。那是临时 `WORKDIR` 和 RUNTIME 隔离的已知现象，不是这次重构引入的。

不要把这张 48/48 写成 StateBench 或 QQ 线上的成功率。
