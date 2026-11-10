"""一次模型请求。不执行工具，也不进入下一轮。"""

from __future__ import annotations

def model_step(
    messages: list,
    tools: list | None = None,
    *,
    max_tokens: int = 5000,
    timeout: int = 180,
    temperature: float | None = None,
    thinking: bool | None = None,
) -> dict:
    from agent.core.loop import chat

    return chat(
        messages,
        tools=tools,
        max_tokens=max_tokens,
        timeout=timeout,
        temperature=temperature,
        thinking=thinking,
    )
