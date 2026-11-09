# 本地演示

命令：

```bash
python scripts/demo_whaleagent.py
```

2026-11-10 这次运行没有调用模型。计划行是本地依赖，不是模型输出。抓到的结论是：

- `s1_parallel_clock_v1` 在重新读取后评分成功，检查点到达。
- 错误正文加 `1999-01-01T00:00:00+08:00` 的轨迹评分失败。
- 来源修订不一致时判定 `reject_source`。
- Vault 与调度器的提交窗口再变化时判定 `residual_race`。
- 200 次故障注入里，重复不可逆效果是 0。
- 测试集未开封，人工复核是 `HUMAN_REVIEW_PENDING`。

回执顺序仍是：STARTED → dispatch → UNKNOWN → 按 `operation_id` 查询 → 确认或停止。同一条轨迹的例子在 [../evaluation/recovery-trace.md](../evaluation/recovery-trace.md)。

同一次冒烟还请求了一次 `deepseek-flash`，只让它回复 OK。接口返回 prompt 33、completion 16，没有 `cached_tokens` 字段，所以缓存记为空。正文是空的，这 16 个 completion 不能当成任务成功。
