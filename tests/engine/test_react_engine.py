"""ReAct 只做一次模型决策，工具由 Engine 执行。不调用真实模型。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.core.loop import agent_loop


class ReactEngineTests(unittest.TestCase):
    def test_tool_call_then_stop_uses_one_executor(self) -> None:
        seen: list[str] = []
        replies = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "echo", "arguments": "{\"text\": \"hi\"}"},
                    }
                ],
            },
            {"role": "assistant", "content": "done"},
        ]

        def fake_step(messages, tools=None, **kwargs):
            _ = messages, tools, kwargs
            return replies.pop(0)

        def echo(text: str) -> str:
            seen.append(text)
            return "ok"

        with patch("agent.policies.react.model_step", fake_step):
            text = agent_loop(
                [{"role": "user", "content": "ping"}],
                tools=[{"type": "function", "function": {"name": "echo", "parameters": {}}}],
                handlers={"echo": echo},
                system_provider=lambda _messages: "test",
                use_mcp=False,
                extract_memory=False,
                todo_reminder=False,
                max_rounds=4,
            )
        self.assertEqual(seen, ["hi"])
        self.assertEqual(text, "done")
        self.assertFalse(replies)
