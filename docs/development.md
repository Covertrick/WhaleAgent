# 开发说明

## 优先级

主线是项目资料协同：同一次 Run 上由 `agent/application` 调用 `decide`。普通 QQ 消息仍走模型循环。v1 冻结题不再改。

1. 先有可重置世界和独立评分器，再改决策规则。
2. 正式五组对照只跑 `evals/statebench`。不把结果建立在异步化之后的 QQ 链路上。
3. 验证集只定一个事先写明的阈值：证据年龄，或下一步是不可逆写入。
4. 目录边界见 [architecture/boundaries.md](./architecture/boundaries.md) 和 [architecture.md](./architecture.md)，逐文件说明见 [files.md](./files.md)。

## 目录与边界

| 目录 | 职责 | 禁止 |
|------|------|------|
| `channel/` | QQ Adapter：听/说、缓存、拦截、限流 | 把隐藏评测事件交给决策器 |
| `core/` | B0：共用的 `agent_loop` 与 `execute_tool` | 感知 OneBot 协议字段 |
| `harness/` | 已冻结的 Run、账本、契约、沙箱 | 依赖 QQ API；被算法包 import |
| `application/` | 项目资料的决策闭环和证据适配 | import channel 或 statebench |
| `algorithms/` | 证据、计划图、观察/修复决策 | import channel、harness 或 statebench |
| `evals/statebench/` | 快照世界、评分、离线步进 | 连接 NapCat |
| `tools/qq.py` / `plugins/` | 线上 Skill 实现与注册 | 绕过账本直接发不可逆副作用 |
| `knowledge/` `files/` `vault/` … | 线上领域数据 | 跨用户读写 |

## 运行

```bash
pip install -r requirements.txt
# agent/.env 至少 API_KEY
python -m agent.smoke_test
python -m unittest tests.algorithm.test_invariants
python -m unittest tests.architecture tests.harness -v
python -m agent                 # QQ Adapter + NapCat 引导
```

## 简历表述

简历可以写：QQ 入口、Harness 上的同一次 Run、证据门控决策，以及项目资料任务里「草稿不重读、提醒写前再取证、未知回执不重放」。

v1 的 40 题数字只按 [evaluation/egaa-v1-results.md](./evaluation/egaa-v1-results.md) 表述，并说明 B2 与每次写前刷新的工具次数相同。v2 真实模型对照还没有结果，见 [evaluation/statebench-v2-protocol.md](./evaluation/statebench-v2-protocol.md)。

不写尚未做的 Multi-Agent、LangGraph、Firecracker、在线自训练。
