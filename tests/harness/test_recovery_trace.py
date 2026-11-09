"""故障注入：回执丢失、同名提醒、超时、重启。不调用模型，不连接 QQ。"""

from __future__ import annotations

import tempfile
import unittest

import agent.config as cfg
from agent.application.workflow import run_project_sync
from agent.harness.adapters import HarnessExecutorAdapter
from agent.harness.effect import IntentStatus, RunStatus
from agent.harness.runtime import HarnessRuntime
from agent.harness.store import HarnessStore
from agent.harness.trace import trace_for
from tests.application.test_project_sync import TEXT, World


class RecoveryTraceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_runtime = cfg.QQ_RUNTIME
        cfg.QQ_RUNTIME = self._tmp.name
        from agent.harness.runtime import _current

        _current.set(None)
        self.store = HarnessStore()
        self.runtime = HarnessRuntime(self.store)

    def tearDown(self) -> None:
        from agent.harness.runtime import _current

        _current.set(None)
        cfg.QQ_RUNTIME = self._old_runtime
        self._tmp.cleanup()

    def _adapter(self, world: World, *, list_text: str) -> HarnessExecutorAdapter:
        created: list[str] = []

        def search_vault(query: str) -> str:
            return str(world.execute("search_vault", {"query": query})["content"])

        def write_vault_draft(topic: str, body: str) -> str:
            return str(world.execute("write_vault_draft", {"topic": topic, "body": body})["content"])

        def schedule_reminder(title: str, due_at: str, category: str = "todo", operation_id: str = "") -> str:
            created.append(operation_id)
            world.calls.append(("schedule_reminder", {"title": title, "due_at": due_at, "operation_id": operation_id}))
            return "UNKNOWN: timeout"

        def schedule_list() -> str:
            world.calls.append(("schedule_list", {}))
            if list_text == "match" and created:
                return f"待办事项 list：\n1. [sch1] [待办] 项目截止 | operation_id={created[0]}"
            if list_text == "other":
                return "待办事项 list：\n1. [sch9] [待办] 项目截止 | operation_id=int_other"
            return "待办事项 list：（空）"

        return HarnessExecutorAdapter(
            {
                "search_vault": search_vault,
                "write_vault_draft": write_vault_draft,
                "schedule_reminder": schedule_reminder,
                "schedule_list": schedule_list,
            }
        )

    def test_matching_operation_id_confirms_without_replay(self) -> None:
        world = World()
        run = self.runtime.start_run(channel="qq", user_id="7", group_id=None, text=TEXT)
        report = run_project_sync(self._adapter(world, list_text="match"), user_text=TEXT)
        reminders = [item for item in world.calls if item[0] == "schedule_reminder"]
        self.assertEqual(len(reminders), 1)
        self.assertTrue(report.goal_verified)
        self.assertEqual(report.run_id, run.run_id)
        intent = next(item for item in run.intents if item.skill == "schedule_reminder")
        self.assertEqual(intent.status, IntentStatus.UNKNOWN.value)
        self.assertIn(intent.intent_id, reminders[0][1]["operation_id"])
        traced = trace_for(run.run_id, self.store)
        assert traced is not None
        self.assertEqual(traced["run_id"], run.run_id)
        self.assertEqual(traced["intents"][0]["intent_id"], run.intents[0].intent_id)
        self.assertTrue(any(item["skill"] == "schedule_list" for item in traced["intents"]))
        self.assertTrue(traced["decisions"])

    def test_same_title_with_another_id_stays_unknown(self) -> None:
        world = World()
        run = self.runtime.start_run(channel="qq", user_id="8", group_id=None, text=TEXT)
        report = run_project_sync(self._adapter(world, list_text="other"), user_text=TEXT)
        reminders = [item for item in world.calls if item[0] == "schedule_reminder"]
        self.assertEqual(len(reminders), 1)
        self.assertFalse(report.goal_verified)
        self.assertEqual(report.termination, "UNVERIFIED")
        self.assertEqual(report.run_id, run.run_id)
        intent = next(item for item in run.intents if item.skill == "schedule_reminder")
        self.assertEqual(intent.status, IntentStatus.UNKNOWN.value)

    def test_timeout_marks_unknown_and_calls_handler_once(self) -> None:
        run = self.runtime.start_run(channel="qq", user_id="9", group_id=None, text="提醒")
        calls: list[str] = []

        def schedule_reminder(title: str, due_at: str, category: str = "todo", operation_id: str = "") -> str:
            calls.append(operation_id)
            raise TimeoutError("lost receipt")

        adapter = HarnessExecutorAdapter({"schedule_reminder": schedule_reminder})
        text = adapter.execute(
            "schedule_reminder",
            {"title": "项目截止", "due_at": "2026-11-10T10:00:00+08:00", "category": "todo"},
        )["content"]
        self.assertEqual(len(calls), 1)
        self.assertIn("不会自动再做", text)
        self.assertEqual(run.intents[-1].status, IntentStatus.UNKNOWN.value)
        self.assertEqual(run.intents[-1].recovery, "ask_user")
        self.assertEqual(run.status, RunStatus.UNKNOWN.value)

    def test_restart_marks_started_unknown_once(self) -> None:
        run = self.runtime.start_run(channel="qq", user_id="10", group_id=None, text="提醒")
        begun = self.runtime.begin_intent(
            run,
            "schedule_reminder",
            {"title": "项目截止", "due_at": "2026-11-10T10:00:00+08:00", "category": "todo"},
        )
        self.assertEqual(begun.status, IntentStatus.STARTED.value)
        restarted = HarnessRuntime(self.store)
        first = restarted.recover_open_runs()
        loaded = self.store.load(run.run_id)
        assert loaded is not None
        self.assertEqual(loaded.status, RunStatus.UNKNOWN.value)
        self.assertEqual(loaded.intents[0].status, IntentStatus.UNKNOWN.value)
        self.assertEqual(len(first), 1)
        second = restarted.recover_open_runs()
        self.assertEqual(second, [])
        self.assertEqual(len(self.store.consume_notices(run.session_key)), 1)

    def test_finish_keeps_unknown_when_receipt_is_unknown(self) -> None:
        run = self.runtime.start_run(channel="qq", user_id="11", group_id=None, text="提醒")

        def schedule_reminder(title: str, due_at: str, category: str = "todo", operation_id: str = "") -> str:
            _ = (title, due_at, category, operation_id)
            return "UNKNOWN: timeout"

        adapter = HarnessExecutorAdapter({"schedule_reminder": schedule_reminder})
        adapter.execute(
            "schedule_reminder",
            {"title": "项目截止", "due_at": "2026-11-10T10:00:00+08:00", "category": "todo"},
        )
        self.runtime.finish(run, status=RunStatus.SUCCEEDED, reply="做完了")
        loaded = self.store.load(run.run_id)
        assert loaded is not None
        self.assertEqual(loaded.status, RunStatus.UNKNOWN.value)
        self.assertEqual(loaded.intents[0].status, IntentStatus.UNKNOWN.value)
