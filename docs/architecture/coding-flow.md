# Coding CLI

入口是 `python -m agent.main`。它不调用 `start_run`。

```text
main
  → CodingExecutorAdapter()          # 整个交互会话复用一个实例
  → agent_loop(history, executor=适配器)
       每轮 assemble_tool_pool(TASK_TOOLS, TOOL_HANDLERS)  # 含 MCP
       每次 tool_call：
         bind_call(id, 当轮 handlers)  # MCP 池会变，所以要换上当轮的表
         execute_tool(..., use_ledger=False)
           PreToolUse（bash / 路径 / mcp__ 的现有钩子）
           不写 QQ intent
           dispatch（snapshot 为空，sandbox_policy 默认 none）
           PostToolUse
```

`use_ledger=False` 只影响这一次 `execute_tool`。它把本地的 `run` 看成没有，不清除 contextvar。子 Agent（`tools/task.py`）仍直接调用 `execute_tool`。QQ 工具表里没有 `task`，Coding CLI 平时也没有当前 Run，所以子调用不会写 QQ 账本。若有人在一个已经 `start_run` 的线程里再跑子 Agent，子调用仍会看见那个 Run。这是已知限制，这次没有改 `task.py`。

## 工具面

父循环的默认工具在 `agent/tools/__init__.py`：`BASE_TOOLS`（bash / read / write / edit / glob）加上 task、todo、任务图、`load_skill`、`connect_mcp`。MCP 工具不写死在这张表里，由 `mcp.assemble_tool_pool` 每轮拼接。

bash 仍是同步的。`run_bash` 忽略 `run_in_background`，后台由 `execute_tool` 里的 `should_run_background` 分发。这次没有把 Coding 工具改成 async。

## 权限

Coding 的拦截在 `agent/hooks/permission.py` 的 `PreToolUse`：危险 bash、可疑命令、越出 `WORKDIR` 的路径、以及 `mcp__` 前缀按 host policy 询问。这和 QQ 的 Skill 契约不是同一张表。QQ 不会因为走了同一个 `execute_tool` 就获得这些工具；QQ 根本不把它们放进 handlers。

## 不注入执行口的调用方

`evals/harness.py` 和 StateBench B0 仍调用 `agent_loop` 且 `executor is None`。那时循环直接 `execute_tool`，有当前 Run 才记账。B0 不会 `start_run`。改默认值会改变冻结基线，所以默认路径留着。
