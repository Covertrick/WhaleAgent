# 工具

## 1. 定位

工具是模型可以点名的函数。QQ 和 Coding 各有一张表，不合并。静态契约（名字、效果类、权限）和运行时是否允许执行，也分开。见 [tool-execution.md](../contracts/tool-execution.md)。

## 2. 代码位置

| 文件 | 是什么 | 不是什么 |
|------|--------|----------|
| `agent/tools/qq.py` | QQ 的 schema、handlers、白名单 | 不是账本 |
| `agent/harness/qq_skills.py` | QQ 名字对应的效果类、权限、版本 | 不是参数 schema |
| `agent/tools/base.py` | Coding 的 bash / read / write / edit / glob，同步 | 不是 QQ 工具 |
| `agent/tools/__init__.py` | Coding 父循环的工具表 | 不包含 QQ 工具 |
| `agent/tools/task.py` | 子 Agent。独立 messages，只用基础工具，最多 30 轮 | 不是任务存储 |
| `agent/tools/task_mgmt.py` | 把 `agent.tasks` 包成返回字符串的 handler | 不是存储，也不是子 Agent |
| `agent/tasks/store.py` | 每个任务一个 JSON，依赖图、认领、完成 | 不是给模型看的 schema |
| `agent/tools/todo.py` | 会话内待办 | 不落 `tasks/` |
| `agent/tools/skill.py` | Coding 的 `load_skill` | 不是 QQ Skill 契约 |
| `agent/tools/mcp_connect.py` | Coding 的 `connect_mcp` | QQ 禁止 |

`tasks/store.py`、`tools/task.py`、`tools/task_mgmt.py` 名字都带 task，职责不同，没有合并。

## 3. 对外接口

QQ：`build_tools(ctx) -> (schemas, handlers)`，并断言 schema、handlers、`QQ_TOOL_NAMES`、契约表一致，且不与 `FORBIDDEN_ON_QQ` 相交。

Coding：`TASK_TOOLS` 与 `TOOL_HANDLERS`。MCP 由 `assemble_tool_pool` 追加。

## 4. 运行流程

模型给出 OpenAI 风格的 `tool_calls`。循环解析 `function.name` 和 `arguments`，交给执行口。执行口最终到 `dispatch`：有 handler 就调用，快照要求 `process` 或 `ast` 时走沙箱。

## 5. 数据与副作用

QQ 工具写记忆、催办、用户沙箱文件、Vault。Coding 工具写 `WORKDIR` 和 `TASKS_DIR` 下的任务 JSON。两边的目录不同。QQ 文件根在 `FILES_DIR/{user_id}/`。

## 6. 并发与恢复

Coding bash 可经 `should_run_background` 进后台，完成通知下一轮注入。QQ 白名单不含 bash。任务 JSON 用独占创建避免 id 冲突。账本恢复不在工具模块里。

## 7. 配置

QQ 工具没有单独的开关表。搜索、嵌入、文件目录来自 `config.py` 和根上的 `search.py` / `embedding.py`。Coding 的工作目录是进程的 `WORKDIR`（当前工作目录解析结果）。

## 8. 测试

架构测试比较契约名、schema 名和 handler 名。冒烟测试调用 `build_tools` 并检查白名单。Coding 工具的 A–F 历史结果在 [coding-af.md](../evaluation/coding-af.md)，不要为了文档重跑在线评测。

## 9. 已知限制

- 契约上的短描述和 schema 里给模型看的长描述可以不一样。测试只锁名字，不锁两段文案相同。
- 插件工具不在 `QQ_TOOL_NAMES` 里。它们的静态字段在各自 `manifest.yaml`，由 `SkillRegistry` 索引。
- Coding 工具没有改成 async。

## 10. 维护规则

- 给 QQ 加工具时同时改 `qq_skills.py` 和 `tools/qq.py`。
- 不要把 `bash` 或 `connect_mcp` 放进 QQ。
- 不要因为三个 task 文件名字相近就合成一个。
