# 文档索引

主线是项目资料协同：QQ 打开一次 Harness Run，选定并冻结一个 Policy，再进入 `agent.engine`。StateBench v1 保留冻结 Runner。v2 复用这个 Engine，不走 NapCat。架构细则在 `architecture/`，和 [architecture.md](./architecture.md) 冲突时以代码和 `architecture/` 为准。

## 架构

| 文档 | 内容 |
|------|------|
| [architecture/overview.md](./architecture/overview.md) | 有哪些系统，各解决什么 |
| [architecture/boundaries.md](./architecture/boundaries.md) | 允许和禁止的依赖 |
| [architecture/runtime-flow.md](./architecture/runtime-flow.md) | 一条 QQ 消息 |
| [architecture/coding-flow.md](./architecture/coding-flow.md) | Coding CLI |
| [architecture/algorithm-flow.md](./architecture/algorithm-flow.md) | 决策闭环：decide、执行器、观察 |
| [architecture/project-sync-loop.md](./architecture/project-sync-loop.md) | 项目资料任务的逐步工具与决策 |
| [architecture/dependency-rules.md](./architecture/dependency-rules.md) | 和架构测试对应的规则 |
| [architecture.md](./architecture.md) | 线上路径摘要（账本、落盘、恢复） |

## 模块

| 文档 | 内容 |
|------|------|
| [modules/harness.md](./modules/harness.md) | Run、账本、沙箱入口 |
| [modules/algorithms.md](./modules/algorithms.md) | `decide` 与原因码 |
| [modules/channel.md](./modules/channel.md) | QQ 适配器 |
| [modules/core.md](./modules/core.md) | 循环与执行口 |
| [modules/tooling.md](./modules/tooling.md) | QQ 工具、Coding 工具、三份 task |
| [modules/plugins-and-skills.md](./modules/plugins-and-skills.md) | 插件索引与 Coding SKILL.md |
| [modules/domains.md](./modules/domains.md) | 记忆、文件、催办、Vault、life |
| [modules/observability.md](./modules/observability.md) | 日志与 token |
| [modules/admin.md](./modules/admin.md) | 控制台路由 |
| [modules/sandbox.md](./modules/sandbox.md) | L1 / L2 |

## 契约

| 文档 | 内容 |
|------|------|
| [contracts/tool-execution.md](./contracts/tool-execution.md) | 静态契约与运行时决定 |
| [contracts/run-lifecycle.md](./contracts/run-lifecycle.md) | Run / Intent 状态 |
| [contracts/action-observation.md](./contracts/action-observation.md) | 决策如何变成线上或模拟动作 |
| [contracts/permissions-and-effects.md](./contracts/permissions-and-effects.md) | QQ 效果类与 Coding 钩子 |

## 评测

| 文档 | 内容 |
|------|------|
| [evaluation/statebench.md](./evaluation/statebench.md) | 任务、环境、Mock / Live、冻结 |
| [evaluation/egaa-v1-results.md](./evaluation/egaa-v1-results.md) | v1 受控规则结果 |
| [evaluation/v2-failure-attribution.md](./evaluation/v2-failure-attribution.md) | v2 开发集六题的失败归因、分阶段 token 和阶段 A–D |
| [evaluation/recovery-trace.md](./evaluation/recovery-trace.md) | 超时、回执丢失、同名提醒、重启的 Run 时间线 |
| [evaluation/v4-reliability.md](./evaluation/v4-reliability.md) | 版本条件和 200 次故障注入 |
| [evaluation/v4-planning-cost.md](./evaluation/v4-planning-cost.md) | 分阶段 token，以及还没跑的规划消融 |
| [evaluation/v3-dataset-audit.md](./evaluation/v3-dataset-audit.md) | 48 个蓝图、96 条实例，开发者已复核 |
| [evaluation/v3-preflight.md](./evaluation/v3-preflight.md) | 开跑前的环境和哈希 |
| [evaluation/v3-planning-ablation.md](./evaluation/v3-planning-ablation.md) | 紧凑计划有代码。正式对比是五组策略，不是紧凑提示 |
| [evaluation/v3-dev-results.md](./evaluation/v3-dev-results.md) | 开发集 120 次，五种策略 |
| [evaluation/v3-validation-selection.md](./evaluation/v3-validation-selection.md) | 验证集按事先规则选中 react@1 |
| [evaluation/v3-frozen-report.md](./evaluation/v3-frozen-report.md) | 测试集 288 次 |
| [evaluation/v3-statistical-analysis.md](./evaluation/v3-statistical-analysis.md) | 按蓝图聚类的置信区间 |
| [demo/run-through.md](./demo/run-through.md) | 不调用模型的本地演示 |
| [adr/0005-evaluation-gates.md](./adr/0005-evaluation-gates.md) | 为什么测试集在人工复核前关闭 |
| [evaluation/statebench-v2-protocol.md](./evaluation/statebench-v2-protocol.md) | v2 协议。线上数字见根目录 README |
| [evaluation/coding-af.md](./evaluation/coding-af.md) | Coding A–F 历史汇总 |
| [evaluation/reproducibility.md](./evaluation/reproducibility.md) | 哪些命令会改写报告 |

## 决策记录

| 文档 | 内容 |
|------|------|
| [adr/0001-modular-monolith.md](./adr/0001-modular-monolith.md) | 不拆服务，不引入第二套 Runtime |
| [adr/0002-execution-boundary.md](./adr/0002-execution-boundary.md) | 注入执行口，账本顺序不变 |
| [adr/0003-algorithm-isolation.md](./adr/0003-algorithm-isolation.md) | 算法包继续隔离 |
| [adr/0004-application-driver.md](./adr/0004-application-driver.md) | 应用层把 decide 接进同一次 Run |

## 操作与计划

| 文档 | 内容 |
|------|------|
| [operations/README.md](./operations/README.md) | 操作文档索引（文件仍在 docs 根上） |
| [files.md](./files.md) | 每个源码文件做什么 |
| [features.md](./features.md) | 已经在线上的能力 |
| [logic-flow.md](./logic-flow.md) | 线上消息、文件、催办 |
| [tech-stack.md](./tech-stack.md) | 技术栈与配置入口 |
| [development.md](./development.md) | 怎么跑 |
| [qq-setup.md](./qq-setup.md) | NapCat 接入 |
| [vault-dashboard.md](./vault-dashboard.md) | Vault 与控制台 |

根目录 [README.md](../README.md) 是产品摘要。
