# 可观测性

## 1. 定位

给运行中的进程留一行日志和按用户累计的 token。不替代 Harness 账本，也不替代 StateBench 轨迹。

## 2. 代码位置

- `agent/observability/logging.py`：`slog(event, **fields)`，JSON 一行
- `agent/observability/usage.py`：按用户 / 群把 token 写入 `usage.db`
- `agent/harness/trace.py`：按 Run 组装轨迹和比率。这是 Harness 的，不是这个包

## 3. 对外接口

`slog` 把 `ts`、`event` 和传入字段打到 stdout；`level=error` 时打到 stderr。编码失败时打一条固定的失败 JSON。

usage 模块被启动路径挂到模型调用上。具体函数以 `usage.py` 为准，这里不复述未在本次阅读中逐行核对的内部辅助函数。

## 4. 运行流程

模型返回后，若挂了 usage 回调，就记 token。`slog` 由调用方显式打点，没有全局自动拦截。Harness 比率由 `admin/metrics.py` 读取 `harness.trace` 和 runtime。

## 5. 数据与副作用

`usage.db` 在 QQ 运行时目录。日志不落文件，只打印。StateBench 的 trace 写在该次运行目录，不进 usage 库。

## 6. 并发与恢复

`slog` 没有队列。usage 写入失败不应被当成工具 UNKNOWN；账本状态以 Harness 为准。

## 7. 配置

没有单独的日志级别环境变量写在 `logging.py` 里。数据库路径跟着 `config.py` 的运行时目录。

## 8. 测试

没有独立的 observability 单测。冒烟和 StateBench 不依赖 `slog` 的输出格式。

## 9. 已知限制

- 日志不是审计账本。UNKNOWN 以 Run 文件为准。
- 本次没有给 `slog` 加新字段。

## 10. 维护规则

- 不要把世界真值或密钥打进日志。
- 不要用日志代替 `complete_intent`。
