# 控制台

## 1. 定位

可选的 FastAPI 控制台，给主人看健康、指标、插件、Run 和自己的记忆 / 催办 / Vault。它不是 agent 的执行入口。

## 2. 代码位置

- `agent/admin/server.py`：应用和路由
- `agent/admin/auth.py`：Magic Link 与 Cookie
- `agent/admin/crud.py`：`/api` 下的记忆、催办、Vault
- `agent/admin/metrics.py`：指标快照
- `agent/admin/tunnel.py`：Cloudflare Quick Tunnel
- `agent/admin/static/dashboard.html`：页面

`QQ_ADMIN_PORT` 为 0 时不启动。启动逻辑在 `agent/__main__.py` 调用的 `maybe_start_admin`。

## 3. 对外接口

`server.py` 上的路由：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康 |
| GET | `/metrics` | 需主人 |
| GET | `/plugins` | 需主人 |
| POST | `/plugins/{name}/reload` | 需主人 |
| GET | `/harness/runs` | 需主人 |
| GET | `/harness/runs/{run_id}` | 需主人 |
| GET | `/sessions` | 需主人 |
| GET | `/` | 根 |
| GET | `/dash` | 页面，可带 token |
| GET | `/api/me` | 需主人 |
| GET | `/api/magic/issue` | 需主人 |

`crud.py` 在 `/api` 下提供 knowledge、schedules、vault 的读写。前缀以 `build_crud_router` 为准。

## 4. 运行流程

控制台在后台线程里服务。它读 Harness 存储和领域存储，不调用 `agent_loop`。重载插件走 `SkillRegistry.reload`，引用计数大于 0 时注册表会拒绝。

## 5. 数据与副作用

CRUD 会改当前用户的记忆、催办和 Vault 文件。这是主人经 HTTP 写的，不是模型工具调用，因此不经过 `execute_tool`。这是现有边界：控制台写和模型写不是同一条账本。

## 6. 并发与恢复

和 OneBot 线程共享进程内的存储单例。没有单独的控制台 Run。

## 7. 配置

`QQ_ADMIN_PORT`、`QQ_ADMIN_SECRET`、`QQ_ADMIN_MAGIC_TTL`（缺省 900 秒）、`QQ_ADMIN_PUBLIC_HOST`、`QQ_ADMIN_BIND`、`QQ_ADMIN_TUNNEL`、`QQ_ADMIN_PUBLIC_URL`。见 `agent/config.py`。

## 8. 测试

没有单独的 admin 单测。不在这次验证里打开控制台或隧道。

## 9. 已知限制

- 端口为 0 等于关闭。
- 本次没有改认证或 CRUD 行为。

## 10. 维护规则

- 不要把控制台变成第二条工具执行 Runtime。
- 不要在未认证路由上暴露 Run 正文或记忆。
