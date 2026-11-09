"""一局 StateBench。检查点在下一次决策前触发，脚本模型只看已经返回的工具结果。"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

from evals.statebench.contracts import CHECKPOINT_NAME
from evals.statebench.environment import Environment
from evals.statebench.traces import TraceWriter


def _message_text(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
    return "\n".join(parts)


def _field(messages: list[dict[str, Any]], label: str) -> str | None:
    match = re.search(label + r"\s+(\S+)", _message_text(messages))
    return match.group(1) if match else None


def state_change_notice(fact_key: str) -> dict[str, Any]:
    return {
        "type": "state_change_notification",
        "fact_key": fact_key,
        "change_detected": True,
        "new_value": None,
    }


def interpret_usage(usage: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str]:
    """供应商没返回用量时保持 null。返回了 0 才记 0。"""
    if isinstance(usage, dict) and any(
        key in usage for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    ):
        return usage, "provider"
    return None, "absent"


def _read_value(messages: list[dict[str, Any]]) -> str | None:
    ids: set[str] = set()
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            if function.get("name") == "read_fact":
                ids.add(str(call.get("id")))
    for message in messages:
        if message.get("role") != "tool" or str(message.get("tool_call_id")) not in ids:
            continue
        try:
            data = json.loads(message.get("content") or "")
        except json.JSONDecodeError:
            continue
        if data.get("ok") and "value" in data:
            return str(data["value"])
    return None


def scripted_reply(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 5000,
    **kwargs: Any,
) -> dict[str, Any]:
    """只根据可见消息行动。写入值只来自 read_fact 的返回，不读取任务答案。"""
    del tools, max_tokens, kwargs
    source = _field(messages, "来源事实")
    target = _field(messages, "写入目标")
    read_ids = _tool_ids(messages, "read_fact")
    write_ids = _tool_ids(messages, "write_fact")
    if source and not read_ids:
        return _tool_message("read_fact", {"fact_key": source}, "read_fact")
    if target and read_ids and not write_ids:
        value = _read_value(messages)
        if value is None:
            return {"role": "assistant", "content": "没有读到来源的值。"}
        return _tool_message("write_fact", {"fact_key": target, "value": value}, "write_fact")
    return {"role": "assistant", "content": "已根据读取结果写入目标。"}


def _tool_ids(messages: list[dict[str, Any]], name: str) -> set[str]:
    found: set[str] = set()
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            if function.get("name") == name:
                found.add(str(call.get("id")))
    answered = {
        str(message.get("tool_call_id"))
        for message in messages
        if message.get("role") == "tool"
    }
    return found & answered


def _tool_message(name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
            }
        ],
    }


def _tool_schema(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


class Episode:
    def __init__(self, task: dict[str, Any], env: Environment, traces: TraceWriter, *, llm: str) -> None:
        self.task = task
        self.env = env
        self.traces = traces
        self.llm = llm
        self.source_key = str(task.get("source_key") or "")
        self.checkpoint_name = str(task.get("checkpoint") or CHECKPOINT_NAME)
        self.checkpoint_pending = False
        self.checkpoint_applied = False
        self.observations: dict[str, list[dict[str, str]]] = {}
        self.writes: list[dict[str, Any]] = []
        self.tool_names: list[str] = []
        self.decision_inputs: list[list[dict[str, Any]]] = []
        self.obs_counter = 1
        self.tool_calls = 0
        self.usage_source = "mock" if llm == "mock" else "absent"
        self.traces.agent({"kind": "goal", "goal": task.get("prompt", "")})
        self.traces.world(
            {
                "kind": "hidden_events",
                "events": [asdict(event) for event in env.events],
                "checkpoint_reached": False,
            }
        )

    def note_decision(self, messages: list[dict[str, Any]]) -> None:
        self.decision_inputs.append(json.loads(json.dumps(messages, ensure_ascii=False)))

    def record_model(
        self,
        message: dict[str, Any],
        *,
        usage: dict[str, Any] | None,
        usage_source: str,
        request: dict[str, Any],
    ) -> None:
        self.usage_source = usage_source
        self.traces.agent(
            {
                "kind": "model_output",
                "model_output": message.get("content"),
                "tool_calls": message.get("tool_calls") or [],
                "usage": usage,
                "usage_source": usage_source,
                "request": request,
                "error": None,
            }
        )

    def before_decision(self, messages: list[dict[str, Any]]) -> list[str]:
        if not self.checkpoint_pending or self.checkpoint_applied:
            return []
        notices = self.env.apply_checkpoint(self.checkpoint_name)
        self.checkpoint_applied = True
        self.checkpoint_pending = False
        visible: list[dict[str, Any]] = []
        for key in notices:
            body = state_change_notice(key)
            messages.append({"role": "user", "content": json.dumps(body, ensure_ascii=False)})
            self.traces.agent({"kind": "notice", **body})
            visible.append(body)
        self.traces.world(
            {
                "kind": "checkpoint",
                "name": self.checkpoint_name,
                "checkpoint_reached": True,
                "notices": visible,
                "truth": self.env.truth,
            }
        )
        return list(notices)

    def finish(self, text: str | None, *, reason: str = "completed") -> None:
        usage: dict[str, int] | None
        if self.llm == "mock":
            usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            usage_source = "mock"
        else:
            usage = None
            usage_source = self.usage_source
        self.traces.agent(
            {
                "kind": "termination",
                "termination_reason": reason,
                "model_output": text,
                "usage": usage,
                "usage_source": usage_source,
                "error": None,
            }
        )
        self.traces.world(
            {
                "kind": "episode_end",
                "checkpoint_reached": self.checkpoint_applied,
                "truth": self.env.truth,
            }
        )

    def allow_tool(self, name: str, budget: int) -> str | None:
        if name not in {"read_fact", "write_fact", "list_facts"}:
            return json.dumps({"ok": False, "error": "tool_not_allowed", "tool": name}, ensure_ascii=False)
        self.tool_calls += 1
        if self.tool_calls > budget:
            return json.dumps({"ok": False, "error": "tool_budget", "tool": name}, ensure_ascii=False)
        self.tool_names.append(name)
        return None

    def provenance(self, target_key: str, value: str, *, committed: bool) -> dict[str, Any]:
        if not self.source_key:
            last = None
            actual = None
            provenance = "provenance_unknown"
        else:
            history = self.observations.get(self.source_key) or []
            row = self.env.get(self.source_key)
            actual = row["version"] if row else None
            if not history:
                last = None
                provenance = "provenance_unknown"
            else:
                last = history[-1]["version"]
                provenance = "observed"
        record = {
            "kind": "write",
            "target_key": target_key,
            "written_value": value,
            "source_key": self.source_key or None,
            "last_observed_source_version": last,
            "actual_source_version_at_write": actual,
            "provenance": provenance,
            "committed": committed,
        }
        self.writes.append(record)
        self.traces.world(record)
        return record


def build_tools(episode: Episode, *, budget: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    def read_fact(fact_key: str) -> str:
        blocked = episode.allow_tool("read_fact", budget)
        if blocked:
            return blocked
        result = episode.env.agent_read(fact_key)
        if result.get("ok"):
            observation_id = f"obs-{episode.obs_counter}"
            episode.obs_counter += 1
            result["observation_id"] = observation_id
            episode.observations.setdefault(fact_key, []).append(
                {
                    "observation_id": observation_id,
                    "version": str(result["version"]),
                    "value": str(result["value"]),
                }
            )
            if fact_key == episode.source_key and not episode.checkpoint_applied:
                episode.checkpoint_pending = True
        episode.traces.agent(
            {
                "kind": "tool_result",
                "tool": "read_fact",
                "arguments": {"fact_key": fact_key},
                "observation_id": result.get("observation_id"),
                "observed_version": result.get("version"),
                "result": result,
                "error": None if result.get("ok") else result.get("error"),
            }
        )
        return json.dumps(result, ensure_ascii=False)

    def write_fact(fact_key: str, value: str) -> str:
        blocked = episode.allow_tool("write_fact", budget)
        if blocked:
            return blocked
        if episode.checkpoint_pending and not episode.checkpoint_applied:
            result = {"ok": False, "error": "await_next_decision", "fact_key": fact_key}
            episode.traces.agent(
                {
                    "kind": "tool_result",
                    "tool": "write_fact",
                    "arguments": {"fact_key": fact_key, "value": value},
                    "result": result,
                    "error": "await_next_decision",
                }
            )
            return json.dumps(result, ensure_ascii=False)
        result = episode.env.agent_write(fact_key, value)
        private = episode.provenance(fact_key, str(value), committed=bool(result.get("ok")))
        episode.traces.agent(
            {
                "kind": "tool_result",
                "tool": "write_fact",
                "arguments": {"fact_key": fact_key, "value": value},
                "result": result,
                "error": None if result.get("ok") else result.get("error"),
                "target_key": private["target_key"],
                "written_value": private["written_value"],
                "source_key": private["source_key"],
                "last_observed_source_version": private["last_observed_source_version"],
            }
        )
        return json.dumps(result, ensure_ascii=False)

    def list_facts() -> str:
        blocked = episode.allow_tool("list_facts", budget)
        if blocked:
            return blocked
        result = {
            "ok": True,
            "readable": sorted(episode.env.readable),
            "writable": sorted(episode.env.writable),
        }
        episode.traces.agent(
            {
                "kind": "tool_result",
                "tool": "list_facts",
                "arguments": {},
                "result": result,
                "error": None,
            }
        )
        return json.dumps(result, ensure_ascii=False)

    tools = [
        _tool_schema(
            "read_fact",
            "读取一个当前可见的事实。",
            {"fact_key": {"type": "string"}},
            ["fact_key"],
        ),
        _tool_schema(
            "write_fact",
            "把一个已观察到的值写入目标事实。",
            {"fact_key": {"type": "string"}, "value": {"type": "string"}},
            ["fact_key", "value"],
        ),
        _tool_schema("list_facts", "列出可读和可写的事实键，不返回值。", {}, []),
    ]
    return tools, {"read_fact": read_fact, "write_fact": write_fact, "list_facts": list_facts}
