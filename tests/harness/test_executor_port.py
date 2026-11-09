"""执行口：QQ 走账本，Coding 不写 QQ 账本。离线，不连模型。"""

from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

import agent.config as cfg
from agent.core.coding_executor import CodingExecutorAdapter
from agent.core.loop import agent_loop
from agent.harness.adapters import HarnessExecutorAdapter
from agent.harness.effect import EffectClass, IntentStatus, RecoveryAction, recovery_for
from agent.harness.runtime import HarnessRuntime, current_run
from agent.harness.store import HarnessStore


class ExecutorPortTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_runtime = cfg.QQ_RUNTIME
        cfg.QQ_RUNTIME = Path(self._tmp.name)
        from agent.harness.runtime import _current

        _current.set(None)
        self.runtime = HarnessRuntime(HarnessStore())

    def tearDown(self) -> None:
        from agent.harness.runtime import _current

        _current.set(None)
        cfg.QQ_RUNTIME = self._old_runtime
        self._tmp.cleanup()

    def test_loop_executor_defaults_to_none(self) -> None:
        self.assertIsNone(inspect.signature(agent_loop).parameters["executor"].default)

    def test_coding_adapter_skips_ledger_while_run_is_current(self) -> None:
        run = self.runtime.start_run(channel="qq", user_id="1", group_id=None, text="cli")
        self.assertIs(current_run(), run)
        adapter = CodingExecutorAdapter()
        adapter.bind_call("call-1", {"echo_tool": lambda: "ok"})
        out = adapter.execute("echo_tool", {})
        self.assertEqual(out["content"], "ok")
        self.assertEqual(run.intents, [])

    def test_harness_adapter_keeps_handlers_and_ledger_order(self) -> None:
        run = self.runtime.start_run(channel="qq", user_id="1", group_id=None, text="搜")
        calls: list[str] = []

        def search(query: str) -> str:
            calls.append(query)
            return "结果A"

        def bash(command: str = "") -> str:
            calls.append("bash:" + command)
            return "no"

        adapter = HarnessExecutorAdapter({"web_search": search})
        adapter.bind_call("call-2", {"bash": bash, "web_search": lambda query: "hijack"})
        out = adapter.execute("web_search", {"query": "x"})
        self.assertEqual(out["content"], "结果A")
        self.assertEqual(calls, ["x"])
        self.assertEqual(run.intents[-1].status, IntentStatus.SUCCEEDED.value)
        self.assertEqual(run.intents[-1].skill, "web_search")

        denied = adapter.execute("bash", {"command": "echo hi"})
        self.assertIn("没有契约", denied["content"])
        self.assertEqual(calls, ["x"])
        self.assertEqual(len(run.intents), 1)

    def test_harness_adapter_refuses_without_run(self) -> None:
        adapter = HarnessExecutorAdapter({"web_search": lambda query: "结果A"})
        out = adapter.execute("web_search", {"query": "x"})
        self.assertIn("拒绝", out["content"])

    def test_unknown_irreversible_is_not_retried_inside_execute(self) -> None:
        self.assertIs(recovery_for(EffectClass.IRREVERSIBLE), RecoveryAction.ASK_USER)
        run = self.runtime.start_run(channel="qq", user_id="1", group_id=None, text="删")
        calls: list[str] = []

        def delete_memory(memory_id: str) -> str:
            calls.append(memory_id)
            return "UNKNOWN: maybe"

        adapter = HarnessExecutorAdapter({"delete_memory": delete_memory})
        out = adapter.execute("delete_memory", {"memory_id": "m1"})
        self.assertEqual(calls, ["m1"])
        self.assertEqual(run.intents[-1].status, IntentStatus.UNKNOWN.value)
        self.assertEqual(run.intents[-1].recovery, RecoveryAction.ASK_USER.value)
        self.assertIn("不会自动再做", out["content"])


if __name__ == "__main__":
    unittest.main()
