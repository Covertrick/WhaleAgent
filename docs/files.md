# 文件职责

路径均相对仓库根目录。`agent/.runtime/` 是运行时落盘，已 gitignore，不在此表。

## 入口与配置

| 文件 | 职责 |
|------|------|
| `agent/__main__.py` | `python -m agent`：引导 NapCat、恢复未完成 Run、挂 usage、启动 OneBot、调度、控制台 |
| `agent/main.py` | `python -m agent.main`：Coding CLI，不进 QQ Run 账本 |
| `agent/demo.py` | 不连 QQ 的本地对话。`g:` 群聊，`p:` 私聊，仍走 `agent_loop` |
| `agent/smoke_test.py` | 离线冒烟：记忆、文件沙箱、催办、QQ 工具白名单、拦截、Harness |
| `agent/config.py` | DeepSeek、OneBot、运行时路径、Vault、向量、限流等环境变量 |
| `agent/.env.example` | 配置模板。启动时若没有 `.env` 会复制一份 |
| `agent/bootstrap_napcat.py` | 补 `.env`、同步 WebUI Token、必要时拉起 NapCat 并等待 WS |
| `agent/webui_login.py` | 用 Token 换 NapCat 登录票，写入浏览器 `localStorage` |
| `agent/http_client.py` | httpx 异步连接池、同步桥、`QQ_FETCH_PROXY` |
| `agent/timeutil.py` | 展示用 Asia/Shanghai，落库用 UTC |
| `agent/embedding.py` | fastembed；按 `QQ_FORCE_SEMANTIC` 失败时回退哈希 |
| `agent/search.py` | DuckDuckGo，失败再走 HTML；`fetch_url` 抽正文。空结果也返回可转述说明 |
| `agent/calendar_sync.py` | 把催办导出为 ICS。OAuth 双向同步只留接口 |
| `agent/scheduler.py` | 装载到期催办，用 APScheduler 的 DateTrigger 到点触发 |
| `agent/user_files.py` | 文件根目录钉在 `FILES_DIR/{user_id}/`，拒绝路径穿越 |
| `requirements.txt` | 运行依赖。fastembed、sqlite-vec、FastAPI、watchdog 在注释里按需安装 |
| `scripts/start_qqbot.ps1` | Windows 下启动 QQ Agent |
| `scripts/open_webui.ps1` | 打开并登录 NapCat WebUI |

## `agent/core/` 与 Coding 侧仍在用的包

QQ 和 Coding CLI 共用循环、LLM 和 `execute_tool`。QQ 传入自己的工具表。

| 文件 | 职责 |
|------|------|
| `contracts/executor.py` | `ToolExecutor` 协议。不选择 QQ 或 Coding，不写账本 |
| `core/loop.py` | 主循环。`executor` 为空时仍调用 `execute_tool`。B0 依赖这条默认路径 |
| `core/execute.py` | 协调：Hook → 若存在当前 Run 且未关闭账本则写 intent → `dispatch` → 收口 |
| `core/coding_executor.py` | Coding CLI 执行口。`use_ledger=False`，工具仍同步 |
| `core/llm.py` | `chat` / `chat_async`，默认走连接池，可挂 usage 回调 |
| `hooks/` | `UserPromptSubmit`、`PreToolUse`、`PostToolUse`、`Stop`。权限钩子对 bash 和越界路径生效 |
| `compaction/compactor.py` | 大输出落盘、剪历史、旧工具结果占位、超限摘要 |
| `memory/memory.py` | Coding CLI 的 Markdown 长期记忆。QQ 不用这条，改走 `knowledge/` |
| `skill_load/loader.py` | 扫描仓库 `skills/*/SKILL.md`，供 Coding CLI 的 `load_skill` |
| `tools/base.py` | Coding 的 bash / read / write / edit / glob |
| `tools/qq.py` | QQ 工具实现与白名单。启动时和 `qq_skills.py` 对一下名字 |
| `tools/task.py` | Coding 子 Agent，独立 messages，只返回摘要。不是任务存储 |
| `tools/todo.py` | Coding 会话内待办 |
| `tools/task_mgmt.py` | 把 `tasks/store.py` 包成工具 handler。不是子 Agent，也不是存储本身 |
| `tools/skill.py` | `load_skill` |
| `tools/mcp_connect.py` | Coding 的 `connect_mcp` |
| `tasks/store.py` | Coding 任务 JSON 与依赖环检测 |
| `background/manager.py` | Coding 后台 bash 与 `<task_notification>` |
| `mcp/` | 进程内 mock MCP（`docs`、`deploy`）和动态工具池。QQ 路径关闭 |

## `agent/harness/`

| 文件 | 职责 |
|------|------|
| `runtime.py` | 开 Run、冻结快照与 guardrails、写 intent、同参数去重、结束 Run、启动时收口未完成 Run |
| `store.py` | Run / Intent / 会话通知的原子 JSON 落盘 |
| `effect.py` | `EffectClass`、Run/Intent 状态、UNKNOWN 时的固定恢复文案 |
| `skill_contract.py` | `SkillManifest` 字段 |
| `qq_skills.py` | 内置 QQ 工具的契约表，版本 `1.0.0`，沙箱默认 `none` |
| `registry.py` | 只扫 `plugins/*/manifest.yaml`，按需 import，引用计数，按 Run 冻结版本 |
| `executor.py` | 按 `sandbox_policy` 分到进程内、L1 或 L2；进程内再跑 postcondition。不是 `core/execute.py` 的别名 |
| `adapters.py` | `HarnessExecutorAdapter`。固定 QQ handlers，调用 `execute_tool`，账本顺序不变 |
| `trace.py` | 按 `run_id` 组装轨迹；统计成功率、UNKNOWN 比例、沙箱失败次数 |
| `sandbox/ast_sandbox.py` | L1：AST 白名单执行 |
| `sandbox/process_sandbox.py` | L2：子进程、超时、工作目录限制 |
| `sandbox/runner.py` | L2 子进程入口，限制网络和越权读 |
| `evolve/whitelist.py` | 只允许改三个约束文件，并拦截 postcondition 里改权限的文本 |
| `evolve/snapshots.py` | 读写真约束、快照、`active_rev` |
| `evolve/enforce.py` | 执行期拦截不可逆重试；在 L1 里跑 `check(result)` |
| `evolve/behavior.py` | 同一回放集上比较旧/新约束，回退则拒绝晋升 |
| `evolve/loop.py` | 失败 trace → 候选约束 → 对照 → 晋升或丢弃 → 可回滚 |
| `evolve/embodied.py` | 模拟 `navigate`（可重试）和 `grasp`（不可逆），用来演示同一套恢复策略 |

## `agent/channel/`

| 文件 | 职责 |
|------|------|
| `onebot.py` | OneBot v11 正向 WebSocket 客户端 |
| `message.py` | 解析文本、@、语音转写、附件 |
| `router.py` | 去重后分流：未 @ 只缓存；@ 和私聊入队 |
| `job_queue.py` | 有界队列和 worker，避免一条消息一个线程 |
| `run.py` | 包一层 Run，预取 URL，冻结 Policy 后进入 Engine，把 UNKNOWN 说明拼进回复 |
| `context.py` | 用户、群、是否群聊等本次请求上下文 |
| `session.py` | 短期多轮历史 |
| `group_cache.py` | 未 @ 消息的滑动窗口；条数过多时做滚动摘要 |
| `prompts.py` | QQ 系统提示：人设、画像、门控后的记忆、群窗口 |
| `intent.py` | 是否注入记忆。默认一次短 LLM 分类，失败再走正则 |
| `intercept.py` | 待办短句、退出、保存上面的文件、文件列表、删除确认等，命中则不进模型 |
| `trust.py` | 把网页和外部内容包进 `<untrusted_content>` |
| `send.py` | 令牌桶、抖动、风控熔断、分片、引用回复 |
| `rate_limit.py` | 全局令牌桶和熔断状态 |
| `health.py` | WS 探活、掉线告警、凭证 401/403 时重读配置 |
| `lifecycle.py` | 异地登录或强制下线时退出全部进程 |
| `proactive.py` | 早报、群关键词命中后私聊主人 |
| `pending.py` | 删除确认等短时内存状态，重启即清空 |
| `file_cache.py` | 「保存上面的文件」用的近期附件缓存 |
| `client_ref.py` | 把正在跑的 OneBot 客户端交给工具侧发文件 |

## 领域包

| 文件 | 职责 |
|------|------|
| `knowledge/store.py` | 按 `private_{uid}` / `group_{gid}` 隔离的情景与语义记忆 |
| `knowledge/profile.py` | `profile.json`：偏好、日期、备注 |
| `knowledge/harvest.py` | 一轮对话结束后判断要不要写入记忆或画像 |
| `knowledge/synthesis.py` | 归纳知识卡片：向量对齐后新建或合并 |
| `knowledge/maintenance.py` | 定时归档，以及情景记忆收成卡片 |
| `files/pipeline.py` | 下载、SHA256 去重、按需摘要、写入索引 |
| `files/index.py` | 文件 SQLite：路径、摘要、标签、引用计数 |
| `files/tags.py` | 发票、合同、简历等规则标签 |
| `files/nl_search.py` | 把「上次那个 PDF」解析成类型和时间条件 |
| `files/delivery.py` | 检索后发送；群里补登；图片可直发 |
| `schedules/store.py` | 催办 SQLite |
| `schedules/rules.py` | 按类别算出多个提醒时间点 |
| `vault/parse.py` | Frontmatter 与切片 |
| `vault/index.py` | `vault.db` 存块；`QQ_VECTOR_BACKEND` 不是 memory/off 时同步到向量索引 |
| `vault/sync.py` | 路径必须留在 Vault 根内；单文件和全库索引 |
| `vault/watcher.py` | watchdog 监听 `.md`，防抖后增量索引 |
| `vault/writer.py` | 模型写笔记、落盘、索引、按配置 git commit |
| `vault/gitops.py` | GitPython 或本机 git |
| `vector/store.py` | sqlite-vec；扩展加载失败则 BLOB 加余弦扫描 |
| `life/capture.py` | 闪念的记入、列表、检索 |
| `life/expense.py` | 从句子里抽金额并按窗口汇总 |
| `life/monitor.py` | RSS / GitHub Release 速递；默认可不调模型 |
| `observability/logging.py` | 一行一条 JSON 日志 |
| `observability/usage.py` | 按用户/群把 token 写入 `usage.db` |

## 控制台与插件

| 文件 | 职责 |
|------|------|
| `admin/server.py` | FastAPI：`/health`、`/metrics`、`/plugins`、`/harness/runs`、`/sessions`、`/dash` |
| `admin/auth.py` | Magic Link 与 Cookie |
| `admin/crud.py` | 当前用户的记忆、待办、Vault 读写 |
| `admin/metrics.py` | 指标快照，含 Harness 比率 |
| `admin/tunnel.py` | Cloudflare Quick Tunnel |
| `admin/static/dashboard.html` | 控制台页面 |
| `plugins/loader.py` | 对注册表的薄封装，兼容旧的插件列表调用 |
| `plugins/echo/` | 示例插件：manifest、回声工具、可 `unregister` 的定时器 |

## `agent/algorithms/`

决策规则。不读取 QQ，也不读取评分器用的世界真值。

| 文件 | 职责 |
|------|------|
| `types.py` | 证据、计划节点、信念、目标、单一风险规则、决策记录 |
| `policies.py` | B0–B4 的开关表 |
| `planner.py` | 下一可执行节点、依赖环 |
| `validator.py` | 前置条件的 `VALID` / `INVALID` / `UNKNOWN` |
| `evidence.py` | 只按已发生的观察更新信念 |
| `invalidation.py` | 按事实键把影响传到后继节点 |
| `repair.py` | 局部修复时保持 `DONE` |
| `controller.py` | 继续、观察、重规划或停止，并写下 `reason_code` |

## `evals/statebench/`

| 文件 | 职责 |
|------|------|
| `environment.py` | 可重置真值。隐藏事件只有 `notify` 时才把事实键交出去 |
| `scorer.py` | 用真值判断目标和过期使用。不看模型自述 |
| `runner.py` | 把通知交给 `decide`，不把真值交给它 |
| `statistics.py` | 配对差和区间。区间含 0 时不能写成稳定提升 |

原 `evals/runner.py` 与 `evals/cases/` 仍是 Coding Harness 的 A–F，不充当 EGAA 对照。

## 评测与技能正文

| 路径 | 职责 |
|------|------|
| `evals/` | Coding Harness 的 A–F 断言 |
| `tests/algorithm/` | 决策不变量，不调用模型 |
| `skills/code-review/` `pdf/` `mcp-builder/` | Coding CLI 按名加载的技能说明 |
| `agent/application/` | 项目资料决策闭环 |
| `docs/evaluation/statebench-v2-protocol.md` | v2 对照协议。线上数字见根目录 README |
| `docs/` | 线上行为说明 |
