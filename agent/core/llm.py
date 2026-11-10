"""LLM 调用：默认走 httpx 异步连接池；提供 chat / chat_async。"""

from __future__ import annotations

from contextvars import ContextVar

from ..config import API_KEY, END_POINT, MODEL_NAME
from ..http_client import async_post_json, http_backend, run_coro, sync_post_json

usage_phase: ContextVar[str] = ContextVar("llm_usage_phase", default="unspecified")

# 评测等可选：每次 chat 后收到 usage dict（若 API 返回）
_usage_hook = None


def set_usage_hook(hook) -> None:
    """注册 usage 回调；传 None 取消。"""
    global _usage_hook
    _usage_hook = hook


def _payload(
    messages: list,
    tools: list | None,
    max_tokens: int,
    temperature: float | None = None,
    thinking: bool | None = None,
) -> dict:
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if thinking is False:
        payload["thinking"] = {"type": "disabled"}
    elif thinking is True:
        payload["thinking"] = {"type": "enabled"}
    if tools is not None:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    return payload


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }


def _apply_usage(data: dict) -> None:
    usage = data.get("usage") or {}
    if _usage_hook is not None:
        _usage_hook(usage)
    if not _phase_recording:
        return
    from agent.core.phase_usage import usage_from_api

    _phase_records.append(usage_from_api(usage, phase=usage_phase.get()))


_phase_recording = False
_phase_records: list = []


def enable_phase_recording() -> None:
    """评测打开后才按阶段记账。平时不留调用记录。"""
    global _phase_recording
    _phase_recording = True


def take_phase_records() -> list:
    """取出并清空已经记下的阶段用量。"""
    rows = list(_phase_records)
    _phase_records.clear()
    return rows


async def chat_async(
    messages: list,
    tools: list | None = None,
    max_tokens: int = 5000,
    timeout: int = 180,
    temperature: float | None = None,
    thinking: bool | None = None,
) -> dict:
    """异步 chat/completions，复用全局 AsyncClient 连接池。"""
    if not END_POINT:
        raise RuntimeError("未配置 BASE_URL / END_POINT")
    data = await async_post_json(
        END_POINT,
        json_body=_payload(messages, tools, max_tokens, temperature, thinking),
        headers=_headers(),
        timeout=float(timeout),
    )
    _apply_usage(data)
    return data["choices"][0]["message"]


def chat(
    messages: list,
    tools: list | None = None,
    max_tokens: int = 5000,
    timeout: int = 180,
    temperature: float | None = None,
    thinking: bool | None = None,
) -> dict:
    """同步入口：在常驻事件循环上调度 chat_async（连接池仍生效）。"""
    if http_backend() == "httpx":
        return run_coro(
            chat_async(
                messages,
                tools=tools,
                max_tokens=max_tokens,
                timeout=timeout,
                temperature=temperature,
                thinking=thinking,
            ),
            timeout=float(timeout) + 10,
        )
    # 极端无 httpx：直连
    data = sync_post_json(
        END_POINT,
        json_body=_payload(messages, tools, max_tokens, temperature, thinking),
        headers=_headers(),
        timeout=float(timeout),
    )
    _apply_usage(data)
    return data["choices"][0]["message"]
