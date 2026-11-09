"""ReAct：一次模型推理决定本步工具或停止。工具由 Engine 执行。"""

from __future__ import annotations

import json
from collections.abc import Callable

from agent.core.model_step import model_step
from agent.engine.events import StepDecision, ToolCall
from agent.engine.runner import StepPolicy


class ReActPolicy(StepPolicy):
    def __init__(
        self,
        messages: list,
        *,
        active_request: str = "",
        tools: list | None = None,
        handlers: dict | None = None,
        system_provider: Callable[[list], str] | None = None,
        use_mcp: bool = True,
        extract_memory: bool = True,
        todo_reminder: bool = True,
    ) -> None:
        self.policy_name = "react"
        self.policy_version = "1"
        self.messages = messages
        self.active_request = active_request
        self.tools = tools
        self.handlers = handlers
        self.system_provider = system_provider
        self.use_mcp = use_mcp
        self.extract_memory = extract_memory
        self.todo_reminder = todo_reminder
        self.pool_handlers: dict = {}
        self.last_text: str | None = None
        self._reactive_retries = 0
        self._rounds_since_todo = 0
        self._model_rounds = 0
        self._pending_calls: list[ToolCall] = []

    def next_step(self) -> StepDecision:
        from agent.compaction import COMPACTOR, MAX_REACTIVE_RETRIES
        from agent.core.loop import _is_http_overflow, _update_system_message
        from agent.hooks import trigger_hook
        from agent.mcp import assemble_tool_pool
        from agent.memory import consolidate_memories, extract_memories
        from agent.tools import TASK_TOOLS, TOOL_HANDLERS
        from agent.background import inject_background_results

        while True:
            inject_background_results(self.messages)
            _update_system_message(self.messages, self.system_provider, use_mcp=self.use_mcp)
            self.messages[:] = COMPACTOR.prepare(self.messages, self.active_request)
            if self.tools is not None and self.handlers is not None:
                pool_tools, pool_handlers = self.tools, self.handlers
                if self.use_mcp:
                    pool_tools, pool_handlers = assemble_tool_pool(self.tools, self.handlers)
            else:
                pool_tools, pool_handlers = assemble_tool_pool(TASK_TOOLS, TOOL_HANDLERS)
            self.pool_handlers = pool_handlers
            try:
                msg = model_step(self.messages, pool_tools, max_tokens=5000)
            except Exception as exc:
                if _is_http_overflow(exc) and self._reactive_retries < MAX_REACTIVE_RETRIES:
                    print("\033[33m[reactive compact] 上下文仍然过长，应急压缩后重试\033[0m")
                    self.messages[:] = COMPACTOR.reactive_compact(self.messages, self.active_request)
                    self._reactive_retries += 1
                    continue
                raise
            break

        self.messages.append(msg)
        if msg.get("content"):
            self.last_text = str(msg["content"]).strip()
        self._model_rounds += 1
        if not msg.get("tool_calls"):
            trigger_hook("Stop", self.messages)
            if self.extract_memory and extract_memories(self.messages):
                consolidate_memories()
            text_out = (self.last_text or "").strip()
            if not text_out and self._model_rounds > 1:
                text_out = "查完了，但这句没写出来。你再说一下想听哪一点。"
            return StepDecision("STOP", answer=text_out, reason_codes=("STOP",))

        calls: list[ToolCall] = []
        for tool_call in msg["tool_calls"]:
            func = tool_call["function"]
            raw = func.get("arguments") or "{}"
            try:
                args = json.loads(raw)
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            calls.append(ToolCall(func["name"], args, str(tool_call.get("id") or "")))
        self._pending_calls = calls
        return StepDecision("CONTINUE", tuple(calls), ("REACT_BASELINE",))

    def on_result(self, call: ToolCall, content: str) -> None:
        self.messages.append(
            {
                "role": "tool",
                "tool_call_id": call.call_id,
                "content": content,
            }
        )
        self._last_was_planning = call.name in {
            "todo_write",
            "create_task",
            "update_task",
            "claim_task",
            "complete_task",
        }

    def on_turn_finished(self) -> None:
        used = any(
            call.name
            in {"todo_write", "create_task", "update_task", "claim_task", "complete_task"}
            for call in self._pending_calls
        )
        if not self.todo_reminder:
            return
        self._rounds_since_todo = 0 if used else self._rounds_since_todo + 1
        if self._rounds_since_todo >= 3:
            self.messages.append(
                {
                    "role": "user",
                    "content": (
                        "<reminder>请用 todo_write 或 "
                        "create_task/claim_task/complete_task 更新任务进度。</reminder>"
                    ),
                }
            )
            self._rounds_since_todo = 0
            print("\033[33m[reminder] 已提醒模型更新任务进度\033[0m")
        self._pending_calls = []
