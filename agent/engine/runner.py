"""唯一的 Agent 步骤循环。策略决定下一步，执行器做副作用。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.engine.events import StepDecision, ToolCall


@dataclass
class EngineResult:
    text: str
    termination: str
    decisions: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    rounds: int = 0
    policy_name: str = ""
    policy_version: str = ""


class StepPolicy:
    """同步策略。next_step 不执行外部工具。"""

    pool_handlers: dict[str, Any]

    def next_step(self) -> StepDecision:
        raise NotImplementedError

    def on_result(self, call: ToolCall, content: str) -> None:
        return None

    def on_turn_finished(self) -> None:
        return None

    def apply_replan(self, decision: StepDecision) -> None:
        return None


def run_engine(policy: StepPolicy, executor, *, max_rounds: int | None = 8) -> EngineResult:
    decisions: list[dict] = []
    tool_calls: list[dict] = []
    rounds = 0
    policy_name = str(getattr(policy, "policy_name", "") or type(policy).__name__)
    policy_version = str(getattr(policy, "policy_version", "1"))
    if not hasattr(policy, "pool_handlers"):
        policy.pool_handlers = {}
    while True:
        if max_rounds is not None and rounds >= max_rounds:
            return EngineResult(
                text=_answer(policy, "处理轮次过多，请把问题拆短一点再试。"),
                termination="MAX_ROUNDS",
                decisions=decisions,
                tool_calls=tool_calls,
                rounds=rounds,
                policy_name=policy_name,
                policy_version=policy_version,
            )
        rounds += 1
        decision = policy.next_step()
        decisions.append(
            {
                "kind": decision.kind,
                "reason_codes": list(decision.reason_codes),
                "answer": decision.answer,
                "tools": [call.name for call in decision.tool_calls],
                **{key: value for key, value in decision.meta.items() if key != "handlers"},
            }
        )
        if decision.kind in {"STOP", "RECOVER"}:
            return EngineResult(
                text=decision.answer or _answer(policy, ""),
                termination=decision.reason_codes[0] if decision.reason_codes else decision.kind,
                decisions=decisions,
                tool_calls=tool_calls,
                rounds=rounds,
                policy_name=policy_name,
                policy_version=policy_version,
            )
        if decision.kind == "REPLAN":
            policy.apply_replan(decision)
            continue
        for call in decision.tool_calls:
            content = _execute(policy, executor, call)
            tool_calls.append({"tool": call.name, "arguments": dict(call.arguments), "content": content})
            policy.on_result(call, content)
        if decision.tool_calls:
            policy.on_turn_finished()


def _execute(policy: StepPolicy, executor, call: ToolCall) -> str:
    if executor is None:
        from agent.core.loop import execute_tool

        return execute_tool(
            call.name,
            dict(call.arguments),
            policy.pool_handlers,
            tool_call_id=call.call_id,
        )
    bind = getattr(executor, "bind_call", None)
    if callable(bind):
        bind(call.call_id or "", policy.pool_handlers)
    result = executor.execute(call.name, dict(call.arguments))
    if isinstance(result, dict):
        content = result.get("content")
        return "" if content is None else str(content)
    return "" if result is None else str(result)


def _answer(policy: StepPolicy, fallback: str) -> str:
    text = getattr(policy, "last_text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    return fallback
