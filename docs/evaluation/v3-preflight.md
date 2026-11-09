# v3 预检

检查时间：2026-11-10。分支 `dev`，当时 HEAD 是 `967cbf6`。远端 `git@github.com:Covertrick/Tiny-Claude-Code.git`。Python 3.12.2。

`agent/.env` 被 `.gitignore` 的 `**/.env` 忽略，`git ls-files` 没有把它列出来。本轮待提交文件里没有发现 `sk-` 开头的密钥。历史是否泄漏见发布报告；这次没有改写 Git 历史。

已核对的代码入口：

- `agent/engine/runner.py` 执行冻结后的 Policy。
- `agent/policies/planning.py` 生成计划。`compact=True` 只收紧字段，不降低 `max_tokens`。
- `agent/application/conditional_write.py` 判断来源修订、目标修订和剩余竞态。
- `evals/statebench/v3/` 现在有 48 个蓝图。v1 冻结文件和 v2 结果文件的 SHA-256 由 `v3/audit.py` 固定，审计不通过就不算数据集有效。

可执行命令：

```bash
python -m evals.statebench.v3.audit
python -m unittest tests.statebench.test_v3_dataset tests.harness.test_fault_matrix -v
python scripts/demo_whaleagent.py
```

一次 `deepseek-flash` 冒烟成功返回用量：prompt 33，completion 16，没有 `cached_tokens`。没有价格表，不能把这次用量换成费用。24 条开发任务乘 5 个策略，以及 288 次正式测试，都还没有跑。

`python -m unittest discover -s tests -q` 在修复 `loop.chat` 兼容入口后为 112 项通过、0 失败。这次修复只把评测垫片接回现有的 `llm.chat` 和 `execute_tool`，没有改 v1 结果文件。
