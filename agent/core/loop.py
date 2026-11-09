"""ReAct 兼容入口。步骤循环在 agent.engine，本函数只组装 ReActPolicy。

模型请求、压缩和记忆提取在 ReActPolicy.next_step。工具执行只发生在 Engine。
"""

from __future__ import annotations

from collections.abc import Callable

import requests

from agent.contracts.executor import ToolExecutor

from ..compaction import is_context_overflow
from ..mcp import mcp_system_addon
from ..memory import build_system, load_memories


def _is_http_overflow(exc: Exception) -> bool:
    httpish = isinstance(exc, requests.HTTPError)
    if not httpish:
        try:
            import httpx

            httpish = isinstance(exc, httpx.HTTPStatusError)
        except Exception:
            httpish = False
    return httpish and is_context_overflow(exc)


def _update_system_message(
    messages: list,
    system_provider: Callable[[list], str] | None = None,
    *,
    use_mcp: bool = True,
) -> None:
    """组装本轮 system。"""
    if system_provider is not None:
        system = system_provider(messages)
    else:
        system = build_system(load_memories(messages))
        if use_mcp:
            addon = mcp_system_addon()
            if addon:
                system = f"{system}\n\n{addon}"
    if messages and messages[0].get("role") == "system":
        messages[0]["content"] = system
    else:
        messages.insert(0, {"role": "system", "content": system})


def agent_loop(
    messages: list,
    active_request: str = "",
    *,
    tools: list | None = None,
    handlers: dict | None = None,
    system_provider: Callable[[list], str] | None = None,
    use_mcp: bool = True,
    extract_memory: bool = True,
    todo_reminder: bool = True,
    max_rounds: int | None = None,
    executor: ToolExecutor | None = None,
) -> str | None:
    """兼容入口。真正的轮次在 Engine，本函数返回最后一条 assistant 文本。"""
    from agent.engine.runner import run_engine
    from agent.policies.react import ReActPolicy

    policy = ReActPolicy(
        messages,
        active_request=active_request,
        tools=tools,
        handlers=handlers,
        system_provider=system_provider,
        use_mcp=use_mcp,
        extract_memory=extract_memory,
        todo_reminder=todo_reminder,
    )
    from agent.application.run_driver import _freeze_policy

    _freeze_policy(policy.policy_name, policy.policy_version)
    result = run_engine(policy, executor, max_rounds=max_rounds)
    text = (result.text or "").strip()
    return text or None
