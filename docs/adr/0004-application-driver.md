# ADR 0004：应用层把 decide 接进同一次 Run

## 状态

接受。取代 ADR 0003 里「不把 decide 接到 QQ Run」这一条。算法包隔离仍然有效。

## 背景

QQ 消息已经会打开 Harness Run，再进入模型循环。EGAA 的 `decide` 以前只在 StateBench 的模拟执行器里被调用。仓库因此同时有一条会执行的模型和一条不会执行的决策器。

## 决定

- 新增 `agent/application`。项目资料任务由 `run_driver` 调用现有 `decide`，再调用已经打开的 Run 上的 `HarnessExecutorAdapter`。
- `run_driver` 不调用完整的 `agent_loop`，也不另开 Run。
- 普通 QQ 消息仍走 `agent_loop`。Coding CLI 仍走自己的执行器。
- `agent/algorithms` 继续禁止 import channel、Harness、StateBench 和 sqlite。
- `agent/application` 禁止 import channel 和 StateBench。`agent/channel` 禁止 import `agent.algorithms`，可以 import 应用层。
- 不改 `decide` 的分支、原因码和 v1 冻结题。
- 显式 `vN` 仍可直接比较。没有来源的文本保持 `UNKNOWN`。同一来源的内容哈希由应用层修订账登记，不在算法包里把哈希当成版本号。来源冲突时不可逆写入停止。
- 账本状态为 `UNKNOWN` 的写入不再由应用层发第二次。
- 2026-11-09 补充：Run 开始时冻结 `policy_name` / `policy_version`。ReAct 与 EGAA 都进入 `agent.engine`，不再各自拥有工具循环。StateBench v1 仍用冻结 Runner。v2 使用同一个 Engine 和模拟适配器。

## 后果

一条项目资料消息可以在同一个 Run ID 下看到决策原因和 Intent。v1 的 40/40 仍是脚本化规则实验。真实模型对照按 `docs/evaluation/statebench-v2-protocol.md` 另行开跑。
