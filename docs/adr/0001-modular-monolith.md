# ADR 0001：模块化单体

## 状态

接受。

## 背景

仓库里同时有 QQ 助手、Coding CLI 和离线评测。把它们拆成服务或再引入一个 Agent 框架，会多出一套运行时，并且让 StateBench 的脚本循环不再是现在这条 `agent_loop`。

## 决定

保持一个进程里的模块化单体。

- Harness 继续负责 QQ 的安全执行和账本。
- `agent/algorithms` 继续只做决策。
- 入口仍是 `agent/__main__.py`、`agent/main.py`、`evals/statebench`。
- 领域包留在现在的目录。根上的 `config`、`http_client`、`embedding`、`search` 仍是共享基础设施。

## 后果

部署和导入都简单。边界要靠测试，而不是靠网络。QQ 与评测的隔离必须写在依赖规则里，不能靠「以后再拆服务」。
