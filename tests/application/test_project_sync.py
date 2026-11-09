"""项目资料工作流。不调用模型，不连接 QQ。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import agent.config as cfg
from agent.algorithms.types import ChangeNotice
from agent.application.evidence_codec import evidence_from_tool, monotonic_version
from agent.application.revisions import ContentRevisionLedger
from agent.application.workflow import project_sync_requested, run_project_sync
from evals.statebench.v2_protocol import HIDDEN_FIELDS, TASKS, visible_task
from agent.harness.adapters import HarnessExecutorAdapter
from agent.harness.effect import IntentStatus
from agent.harness.runtime import HarnessRuntime, current_run
from agent.harness.store import HarnessStore
from agent.harness.trace import trace_for


TEXT = (
    "帮我整理最近的项目会议资料，生成待办清单写进 Vault，根据最新截止时间创建提醒。\n"
    "遇到信息冲突先核实，完成后告诉我哪些操作成功、哪些还需要确认。"
)


class World:
    def __init__(self) -> None:
        self.facts = {
            "project.materials": {"version": "v1", "value": "纪要A", "uri": "vault://meeting"},
            "project.deadline": {
                "version": "v1",
                "value": "2026-11-10T10:00:00+08:00",
                "uri": "vault://meeting#deadline",
            },
        }
        self.calls: list[tuple[str, dict]] = []
        self.reminder = "ok"

    def execute(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, dict(arguments)))
        if name == "search_vault":
            key = "project.materials" if "资料" in arguments.get("query", "") else "project.deadline"
            item = self.facts[key]
            if item.get("digest"):
                return {
                    "content": (
                        "EVIDENCE\n"
                        f"fact_key: {key}\n"
                        f"content_sha256: {item['digest']}\n"
                        f"value: {item['value']}\n"
                        f"source_uri: {item['uri']}\n"
                    )
                }
            if not item["version"]:
                return {"content": f"Vault 检索：\n- 笔记\n  {item['value']}"}
            return {
                "content": (
                    "EVIDENCE\n"
                    f"fact_key: {key}\n"
                    f"source_version: {item['version']}\n"
                    f"value: {item['value']}\n"
                    f"source_uri: {item['uri']}\n"
                )
            }
        if name == "write_vault_draft":
            return {"content": "已写入 Vault：notes/draft.md"}
        if name == "schedule_reminder":
            if self.reminder == "unknown":
                return {"content": "UNKNOWN: timeout"}
            return {"content": f"已加入任务列表 id=sch1\n到期：{arguments['due_at']}"}
        if name == "schedule_list":
            return {"content": "待办事项 list：（空）"}
        return {"content": f"Error: 未知工具 {name}"}


def _hashed(uri: str, value: str, digest: str) -> str:
    return (
        "EVIDENCE\n"
        "fact_key: project.deadline\n"
        f"content_sha256: {digest}\n"
        f"value: {value}\n"
        f"source_uri: {uri}\n"
    )


def _count(world: World, tool: str, query: str = "") -> int:
    total = 0
    for name, arguments in world.calls:
        if name != tool:
            continue
        if query and query not in str(arguments.get("query", "")):
            continue
        total += 1
    return total


class ProjectSyncTests(unittest.TestCase):
    def test_ordinary_chat_stays_on_the_model_loop(self) -> None:
        self.assertFalse(project_sync_requested("你好"))
        self.assertFalse(project_sync_requested("整理一下房间"))
        self.assertTrue(project_sync_requested(TEXT))

    def test_hash_is_not_a_sortable_version(self) -> None:
        self.assertIsNone(monotonic_version("sha256:" + "a" * 64))
        item = evidence_from_tool(
            fact_key="project.materials",
            content="content_sha256: " + "ab" * 32,
            observed_at=0,
        )
        self.assertEqual(item.status, "UNKNOWN")
        self.assertEqual(item.source_version, "unversioned")

    def test_same_content_hash_keeps_one_revision(self) -> None:
        ledger = ContentRevisionLedger()
        body = _hashed("vault://deadline.md", "2026-11-10T10:00:00+08:00", "aa" * 32)
        first = evidence_from_tool(
            fact_key="project.deadline", content=body, observed_at=1, ledger=ledger
        )
        second = evidence_from_tool(
            fact_key="project.deadline", content=body, observed_at=2, ledger=ledger
        )
        changed = evidence_from_tool(
            fact_key="project.deadline",
            content=_hashed("vault://deadline.md", "2026-11-12T15:00:00+08:00", "bb" * 32),
            observed_at=3,
            ledger=ledger,
        )
        self.assertEqual(first.status, "VALID")
        self.assertEqual(first.source_version, "v1")
        self.assertEqual(second.source_version, "v1")
        self.assertEqual(changed.source_version, "v2")
        self.assertEqual(changed.status, "VALID")

    def test_two_sources_with_different_values_stay_unknown(self) -> None:
        ledger = ContentRevisionLedger()
        first = evidence_from_tool(
            fact_key="project.deadline",
            content=_hashed("vault://a.md", "2026-11-10T10:00:00+08:00", "aa" * 32),
            observed_at=1,
            ledger=ledger,
        )
        second = evidence_from_tool(
            fact_key="project.deadline",
            content=_hashed("vault://b.md", "2026-11-12T15:00:00+08:00", "bb" * 32),
            observed_at=2,
            ledger=ledger,
        )
        self.assertEqual(first.status, "VALID")
        self.assertEqual(second.status, "UNKNOWN")

    def test_content_hash_can_support_a_reminder(self) -> None:
        world = World()
        world.facts["project.deadline"] = {
            "version": "",
            "value": "2026-11-10T10:00:00+08:00",
            "uri": "vault://deadline.md",
            "digest": "cc" * 32,
        }
        report = run_project_sync(world, user_text=TEXT)
        self.assertTrue(report.goal_verified)
        reminder = [arguments for name, arguments in world.calls if name == "schedule_reminder"]
        self.assertEqual(
            reminder,
            [{"title": "项目截止", "due_at": "2026-11-10T10:00:00+08:00", "category": "todo"}],
        )

    def test_selective_refresh_skips_the_reversible_draft(self) -> None:
        selective = World()
        always = World()
        left = run_project_sync(selective, user_text=TEXT, policy="B2")
        right = run_project_sync(always, user_text=TEXT, policy="B3")
        self.assertTrue(left.goal_verified)
        self.assertTrue(right.goal_verified)
        self.assertEqual(_count(selective, "search_vault", "资料"), 1)
        self.assertEqual(_count(always, "search_vault", "资料"), 2)
        self.assertEqual(_count(selective, "write_vault_draft"), 1)
        self.assertEqual(_count(selective, "schedule_reminder"), 1)
        self.assertTrue(any("POTENTIALLY_STALE" in item["reason_codes"] for item in left.decisions))
        self.assertTrue(any("ALWAYS_REFRESH" in item["reason_codes"] for item in right.decisions))
        self.assertFalse(any("ALWAYS_REFRESH" in item["reason_codes"] for item in left.decisions))

    def test_deadline_change_keeps_the_finished_draft(self) -> None:
        world = World()
        injected = {"done": False}

        def before_decision(now: int, nodes: list) -> list[ChangeNotice]:
            draft = next(node for node in nodes if node.id == "write_draft")
            if draft.status != "DONE" or injected["done"]:
                return []
            injected["done"] = True
            world.facts["project.deadline"] = {
                "version": "v2",
                "value": "2026-11-12T15:00:00+08:00",
                "uri": "vault://meeting#deadline",
            }
            return [ChangeNotice("deadline-changed", "project.deadline", now)]

        report = run_project_sync(world, user_text=TEXT, before_decision=before_decision)
        self.assertTrue(report.goal_verified)
        self.assertEqual(_count(world, "write_vault_draft"), 1)
        self.assertEqual(_count(world, "search_vault", "资料"), 1)
        reminder = [arguments for name, arguments in world.calls if name == "schedule_reminder"]
        self.assertEqual(reminder, [{"title": "项目截止", "due_at": "2026-11-12T15:00:00+08:00", "category": "todo"}])

    def test_unversioned_deadline_does_not_create_a_reminder(self) -> None:
        world = World()
        world.facts["project.deadline"]["version"] = ""
        report = run_project_sync(world, user_text=TEXT)
        self.assertFalse(report.goal_verified)
        self.assertEqual(_count(world, "schedule_reminder"), 0)
        self.assertIn("schedule.reminder", report.needs_confirmation)
        self.assertEqual(report.termination, "EVIDENCE_UNKNOWN")
        self.assertEqual(_count(world, "search_vault", "截止"), 1)
        self.assertEqual(_count(world, "write_vault_draft"), 1)

    def test_v2_visible_task_drops_answer_keys(self) -> None:
        for task in TASKS:
            view = visible_task(task)
            self.assertTrue(HIDDEN_FIELDS.isdisjoint(view))
        with self.assertRaises(ValueError):
            visible_task({"task_id": "x", "prompt": "y", "source_key": "secret"})

    def test_unknown_reminder_is_not_sent_twice(self) -> None:
        world = World()
        world.reminder = "unknown"
        report = run_project_sync(world, user_text=TEXT)
        self.assertEqual(report.termination, "UNVERIFIED")
        self.assertEqual(_count(world, "schedule_reminder"), 1)
        self.assertEqual(_count(world, "schedule_list"), 1)
        self.assertIn("没有再创建一次", report.reply)
        self.assertFalse(report.goal_verified)


class HarnessWorkflowTests(unittest.TestCase):
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

    def _handlers(self, world: World) -> dict:
        def search_vault(query: str) -> str:
            return str(world.execute("search_vault", {"query": query})["content"])

        def write_vault_draft(topic: str, body: str) -> str:
            return str(world.execute("write_vault_draft", {"topic": topic, "body": body})["content"])

        def schedule_reminder(title: str, due_at: str, category: str = "todo") -> str:
            return str(
                world.execute(
                    "schedule_reminder",
                    {"title": title, "due_at": due_at, "category": category},
                )["content"]
            )

        def schedule_list() -> str:
            return str(world.execute("schedule_list", {})["content"])

        return {
            "search_vault": search_vault,
            "write_vault_draft": write_vault_draft,
            "schedule_reminder": schedule_reminder,
            "schedule_list": schedule_list,
        }

    def test_one_run_links_decisions_and_intents(self) -> None:
        world = World()
        run = self.runtime.start_run(channel="qq", user_id="7", group_id=None, text=TEXT)
        report = run_project_sync(HarnessExecutorAdapter(self._handlers(world)), user_text=TEXT)
        self.assertEqual(report.run_id, run.run_id)
        self.assertTrue(report.goal_verified)
        skills = [intent.skill for intent in run.intents]
        self.assertEqual(skills.count("schedule_reminder"), 1)
        self.assertIn("write_vault_draft", skills)
        self.assertIn("search_vault", skills)
        self.assertTrue(all(intent.status == IntentStatus.SUCCEEDED.value for intent in run.intents))
        traced = trace_for(run.run_id, self.runtime.store)
        self.assertIsNotNone(traced)
        assert traced is not None
        self.assertEqual(traced["run_id"], run.run_id)
        self.assertTrue(traced["decisions"])
        self.assertEqual(run.policy_name, "egaa")
        self.assertEqual(run.policy_version, "2")
        with self.assertRaises(RuntimeError):
            self.runtime.bind_policy(run, "react", "1")
        with self.assertRaises(RuntimeError):
            self.runtime.bind_policy(run, "egaa", "1")
        self.assertIs(current_run(), run)

    def test_unknown_intent_stays_on_the_same_run(self) -> None:
        world = World()
        world.reminder = "unknown"
        run = self.runtime.start_run(channel="qq", user_id="7", group_id=None, text=TEXT)
        report = run_project_sync(HarnessExecutorAdapter(self._handlers(world)), user_text=TEXT)
        reminder = [intent for intent in run.intents if intent.skill == "schedule_reminder"]
        self.assertEqual(len(reminder), 1)
        self.assertEqual(reminder[0].status, IntentStatus.UNKNOWN.value)
        self.assertEqual(report.run_id, run.run_id)
        self.assertEqual(report.termination, "UNVERIFIED")
        listed = [intent for intent in run.intents if intent.skill == "schedule_list"]
        self.assertEqual(len(listed), 1)


if __name__ == "__main__":
    unittest.main()
