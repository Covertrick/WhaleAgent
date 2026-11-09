"""D1–D3。T01–T16 后续不删。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evals.statebench.audit import (
    agent_view_problems,
    blueprint_cross_splits,
    hash_problems,
    run_audit,
)
from evals.statebench.catalog import (
    SEED_IDS,
    agent_payload,
    build_catalog,
    load_manifest,
    load_seeds,
    load_splits,
    load_task,
    load_tasks,
)
from evals.statebench.contracts import CHECKPOINT_CONTRACT, SCORING_CONTRACT
from evals.statebench.environment import Environment
from evals.statebench.episode import build_tools, interpret_usage
from evals.statebench.hashing import sha256_json, sha256_text
from evals.statebench.imports_scan import scan_source, scan_static_channel_imports
from evals.statebench.scorer import assertion_holds, false_invalidation_metric
from evals.statebench.traces import TraceWriter, read_jsonl


def _runs(task_id: str, **kwargs):
    from evals.statebench.b0 import run_b0

    return run_b0(task_id, llm="mock", **kwargs)


def _text(result: dict, name: str) -> str:
    return (Path(result["trace_dir"]) / name).read_text(encoding="utf-8")


class StateBenchTests(unittest.TestCase):
    def test_t01_mock_uses_real_loop_and_ignores_answers(self) -> None:
        from agent.core import llm as llm_mod
        from agent.core import loop as loop_mod
        from agent import http_client

        task = load_task("s0_meeting_a")
        task["expected"] = "HIDDEN_SENTINEL_42"
        task["events"] = [
            {
                "checkpoint": task["checkpoint"],
                "fact_key": task["source_key"],
                "value": "HIDDEN_SENTINEL_42",
                "version": "v9",
                "notify": True,
            }
        ]
        loop_calls: list[dict] = []
        tool_calls: list[str] = []
        network: list[str] = []
        real_loop = loop_mod.agent_loop
        real_execute = loop_mod.execute_tool

        def spy_loop(*args, **kwargs):
            loop_calls.append(kwargs)
            return real_loop(*args, **kwargs)

        def spy_execute(name, args, handlers, tool_call_id=""):
            tool_calls.append(name)
            return real_execute(name, args, handlers, tool_call_id=tool_call_id)

        def boom(*args, **kwargs):
            network.append("called")
            raise AssertionError("mock requested the network")

        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch.object(loop_mod, "agent_loop", spy_loop),
                patch.object(loop_mod, "execute_tool", spy_execute),
                patch.object(llm_mod, "chat", boom),
                patch.object(llm_mod, "async_post_json", boom),
                patch.object(http_client, "async_post_json", boom),
                patch.object(http_client, "sync_post_json", boom),
            ):
                result = _runs("s0_meeting_a", task=task, workspace=temporary)
            try:
                self.assertEqual(len(loop_calls), 1)
                self.assertFalse(loop_calls[0]["use_mcp"])
                self.assertFalse(loop_calls[0]["extract_memory"])
                self.assertFalse(loop_calls[0]["todo_reminder"])
                self.assertEqual(loop_calls[0]["max_rounds"], 6)
                self.assertIn("read_fact", tool_calls)
                self.assertIn("write_fact", tool_calls)
                self.assertGreater(len(tool_calls), 0)
                self.assertEqual(network, [])
                agent_rows = read_jsonl(Path(result["trace_dir"]) / "agent_trace.jsonl")
                world_rows = read_jsonl(Path(result["trace_dir"]) / "world_trace.jsonl")
                self.assertTrue(agent_rows)
                self.assertTrue(all(row["schema"] == "statebench-trace-v1" for row in agent_rows + world_rows))
                visible = _text(result, "agent_trace.jsonl") + _text(result, "trace.jsonl")
                visible += json.dumps(result["decision_inputs"], ensure_ascii=False)
                self.assertNotIn("HIDDEN_SENTINEL_42", visible)
                self.assertNotIn("actual_source_version_at_write", visible)
                self.assertIn("HIDDEN_SENTINEL_42", _text(result, "world_trace.jsonl"))
                self.assertEqual(result["env"].get(task["target_key"])["value"], "15:00")
                model_rows = [row for row in agent_rows if row["kind"] == "model_output"]
                self.assertTrue(model_rows)
                self.assertEqual(model_rows[0]["usage_source"], "mock")
                self.assertEqual(model_rows[0]["usage"]["total_tokens"], 0)
            finally:
                result["env"].close()

    def test_t02_mock_runs_without_api_key(self) -> None:
        from agent import config
        from agent.core import llm as llm_mod

        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch.object(config, "API_KEY", ""),
                patch.object(llm_mod, "API_KEY", ""),
                patch.dict(os.environ, {"API_KEY": "", "STATEBENCH_LLM": "mock"}),
            ):
                result = _runs("s0_meeting_a", workspace=temporary)
            try:
                self.assertEqual(result["llm"], "mock")
                self.assertTrue(result["tool_names"])
                self.assertEqual(result["score"]["false_invalidations"], "not_applicable")
            finally:
                result["env"].close()

    def test_t03_reset_hash_is_stable(self) -> None:
        env = Environment({"meeting.time": {"value": "15:00", "version": "v1"}})
        try:
            token = env.snapshot_token()
            env.reset()
            self.assertEqual(env.snapshot_token(), token)
            env.reset()
            self.assertEqual(env.snapshot_token(), token)
            db_hash = __import__("hashlib").sha256((env.root / "world.sqlite").read_bytes()).hexdigest()
            self.assertNotEqual(token, db_hash)
            escaped = env._mirror_path("../secret")
            self.assertEqual(escaped.parent, env.root / "files")
            self.assertNotIn("..", escaped.parts)
        finally:
            env.close()

    def test_t04_reset_restores_sqlite_and_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env = Environment(
                [{"key": "meeting.time", "value": "15:00", "version": "v1"}],
                root=temporary,
            )
            try:
                token = env.snapshot_token()
                self.assertIsNotNone(env._conn)
                env._conn.execute("UPDATE facts SET value = ? WHERE fact_key = ?", ("99:00", "meeting.time"))
                env._conn.commit()
                env._mirror_path("meeting.time").write_text("tampered\n", encoding="utf-8")
                env.reset()
                self.assertEqual(env.snapshot_token(), token)
                self.assertEqual(env.get("meeting.time")["value"], "15:00")
            finally:
                env.close()

    def test_t05_s0_writes_the_observed_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = _runs("s0_meeting_a", workspace=temporary)
            try:
                task = load_task("s0_meeting_a")
                initial = {item["key"]: item["value"] for item in task["initial_facts"]}
                self.assertTrue(result["score"]["goal_met"])
                self.assertEqual(result["score"]["stale_source_writes"], 0)
                self.assertEqual(result["score"]["wrong_final_values"], 0)
                self.assertTrue(result["score"]["checkpoint_reached"])
                self.assertEqual(
                    result["env"].get(task["target_key"])["value"],
                    initial[task["source_key"]],
                )
                world = read_jsonl(Path(result["trace_dir"]) / "world_trace.jsonl")
                writes = [row for row in world if row["kind"] == "write" and row["committed"]]
                self.assertEqual(writes[0]["last_observed_source_version"], "v1")
                self.assertEqual(writes[0]["actual_source_version_at_write"], "v1")
            finally:
                result["env"].close()

    def test_t06_s1_notice_has_no_new_value_and_counts_are_separate(self) -> None:
        task = load_task("s1_meeting_a")
        secret = task["events"][0]["value"]
        with tempfile.TemporaryDirectory() as temporary:
            result = _runs("s1_meeting_a", workspace=temporary)
            try:
                contents = [
                    message.get("content", "")
                    for message in result["decision_inputs"][1]
                    if isinstance(message.get("content"), str)
                ]
                view = "\n".join(contents)
                self.assertIn("state_change_notification", view)
                self.assertIn('"new_value": null', view)
                self.assertNotIn(secret, view)
                self.assertNotIn(secret, _text(result, "agent_trace.jsonl"))
                self.assertIn(secret, _text(result, "world_trace.jsonl"))
                self.assertGreaterEqual(result["score"]["stale_source_writes"], 1)
                self.assertGreaterEqual(result["score"]["wrong_final_values"], 1)
                self.assertFalse(result["score"]["goal_met"])
                self.assertEqual(result["score"]["false_invalidations"], "not_applicable")
            finally:
                result["env"].close()

    def test_same_turn_write_waits_for_the_next_decision(self) -> None:
        task = load_task("s1_meeting_a")
        secret = task["events"][0]["value"]
        with tempfile.TemporaryDirectory() as temporary:
            env = Environment(
                task["initial_facts"],
                task["events"],
                Path(temporary) / "world",
                readable=task["readable"],
                writable=task["writable"],
                env_only=task["env_only"],
            )
            episode_traces = TraceWriter(Path(temporary) / "traces")
            from evals.statebench.episode import Episode

            episode = Episode(task, env, episode_traces, llm="mock")
            _tools, handlers = build_tools(episode, budget=8)
            try:
                observed = json.loads(handlers["read_fact"](fact_key=task["source_key"]))
                rejected = json.loads(
                    handlers["write_fact"](fact_key=task["target_key"], value=observed["value"])
                )
                self.assertEqual(rejected["error"], "await_next_decision")
                self.assertIsNone(env.get(task["target_key"]))
                messages: list[dict] = []
                episode.before_decision(messages)
                self.assertIn("state_change_notification", messages[0]["content"])
                self.assertNotIn(secret, messages[0]["content"])
                accepted = json.loads(
                    handlers["write_fact"](fact_key=task["target_key"], value=observed["value"])
                )
                self.assertTrue(accepted["ok"])
            finally:
                env.close()

    def test_t07_s2_unrelated_change_keeps_the_goal(self) -> None:
        task = load_task("s2_meeting_a")
        secret = task["events"][0]["value"]
        with tempfile.TemporaryDirectory() as temporary:
            result = _runs("s2_meeting_a", workspace=temporary)
            try:
                self.assertTrue(result["score"]["goal_met"])
                self.assertEqual(result["score"]["stale_source_writes"], 0)
                notices = [
                    row
                    for row in read_jsonl(Path(result["trace_dir"]) / "agent_trace.jsonl")
                    if row["kind"] == "notice"
                ]
                self.assertEqual(notices[0]["fact_key"], task["events"][0]["fact_key"])
                self.assertIsNone(notices[0]["new_value"])
                self.assertNotIn(secret, json.dumps(notices[0], ensure_ascii=False))
                self.assertEqual(
                    result["env"].get(task["source_key"])["value"],
                    task["initial_facts"][0]["value"],
                )
            finally:
                result["env"].close()

    def test_t08_s3_hides_the_notice_and_keeps_the_new_version(self) -> None:
        task = load_task("s3_meeting_a")
        with tempfile.TemporaryDirectory() as temporary:
            s0 = _runs("s0_meeting_a", workspace=Path(temporary) / "s0")
            s3 = _runs("s3_meeting_a", workspace=Path(temporary) / "s3")
            try:
                self.assertEqual(s0["decision_inputs"][1], s3["decision_inputs"][1])
                self.assertNotIn("state_change_notification", _text(s3, "agent_trace.jsonl"))
                world = read_jsonl(Path(s3["trace_dir"]) / "world_trace.jsonl")
                versions = [
                    row["truth"][task["source_key"]]["version"]
                    for row in world
                    if row.get("truth") and task["source_key"] in row["truth"]
                ]
                self.assertIn(task["events"][0]["version"], versions)
                self.assertFalse(s3["score"]["goal_met"])
                self.assertGreaterEqual(s3["score"]["stale_source_writes"], 1)
            finally:
                s0["env"].close()
                s3["env"].close()

    def test_t09_bad_keys_return_structured_errors(self) -> None:
        env = Environment(
            [{"key": "meeting.time", "value": "15:00", "version": "v1"}],
            readable=["meeting.time"],
            writable=["reminder.time"],
        )
        try:
            self.assertEqual(env.agent_read("no.such")["error"], "not_readable")
            self.assertEqual(env.agent_read("../secret")["error"], "not_readable")
            with tempfile.TemporaryDirectory() as temporary:
                traces = TraceWriter(temporary)
                from evals.statebench.episode import Episode

                episode = Episode(
                    {"source_key": "meeting.time", "prompt": "来源事实 meeting.time 。写入目标 reminder.time 。"},
                    env,
                    traces,
                    llm="mock",
                )
                _tools, handlers = build_tools(episode, budget=8)
                listed = json.loads(handlers["list_facts"]())
                self.assertEqual(listed["readable"], ["meeting.time"])
                self.assertEqual(listed["writable"], ["reminder.time"])
                self.assertNotIn("15:00", json.dumps(listed))
            env.readable.add("missing.key")
            self.assertEqual(env.agent_read("missing.key")["error"], "missing_key")
        finally:
            env.close()

    def test_t10_writing_the_source_is_rejected(self) -> None:
        env = Environment(
            [{"key": "meeting.time", "value": "15:00", "version": "v1"}],
            readable=["meeting.time"],
            writable=["reminder.time"],
            env_only=["meeting.time"],
        )
        try:
            rejected = env.agent_write("meeting.time", "99:00")
            self.assertFalse(rejected["ok"])
            self.assertEqual(rejected["error"], "not_writable")
            self.assertEqual(env.get("meeting.time")["value"], "15:00")
            self.assertEqual(len(env.rejected), 1)
            self.assertEqual(env.illegal_committed, 0)
        finally:
            env.close()

    def test_t11_equals_fact_uses_the_final_truth(self) -> None:
        env = Environment(
            [{"key": "meeting.time", "value": "16:00", "version": "v2"}],
            readable=["meeting.time"],
            writable=["reminder.time"],
            env_only=["meeting.time"],
        )
        try:
            env.agent_write("reminder.time", "15:00")
            self.assertTrue(
                assertion_holds({"type": "equals_literal", "key": "reminder.time", "value": "15:00"}, env)
            )
            self.assertFalse(
                assertion_holds(
                    {"type": "equals_fact", "left": "reminder.time", "right": "meeting.time"},
                    env,
                )
            )
            env.agent_write("reminder.time", "16:00")
            self.assertTrue(
                assertion_holds(
                    {"type": "equals_fact", "left": "reminder.time", "right": "meeting.time"},
                    env,
                )
            )
            self.assertTrue(assertion_holds({"type": "exists", "key": "reminder.time"}, env))
            self.assertTrue(
                assertion_holds({"type": "count_equals", "key": "reminder.time", "count": 2}, env)
            )
            self.assertEqual(false_invalidation_metric(None, env), "not_applicable")
        finally:
            env.close()

    def test_t12_cross_split_blueprint_fails(self) -> None:
        tasks = [
            {"task_id": "s0_meeting_a", "blueprint_id": "bp_shared"},
            {"task_id": "s0_meeting_b", "blueprint_id": "bp_shared"},
        ]
        splits = {"dev": ["s0_meeting_a"], "val": ["s0_meeting_b"], "test": []}
        self.assertEqual(blueprint_cross_splits(tasks, splits), ["bp_shared"])
        real = blueprint_cross_splits(load_tasks(), load_splits())
        self.assertEqual(real, [])
        catalog = build_catalog()
        self.assertEqual(len(catalog["tasks"]), 80)
        self.assertEqual(len({task["blueprint_id"] for task in catalog["tasks"]}), 40)
        self.assertEqual({name: len(ids) for name, ids in catalog["splits"].items()}, {"dev": 24, "val": 16, "test": 40})
        self.assertEqual([task["task_id"] for task in catalog["seeds"]], list(SEED_IDS))

    def test_t13_changed_task_breaks_the_manifest(self) -> None:
        tasks = load_tasks()
        splits = load_splits()
        seeds = load_seeds()
        manifest = load_manifest()
        self.assertEqual(hash_problems(tasks, splits, seeds, manifest), [])
        changed = json.loads(json.dumps(tasks))
        changed[0]["prompt"] += "改"
        self.assertIn("tasks", hash_problems(changed, splits, seeds, manifest))
        self.assertNotEqual(sha256_json(changed), manifest["tasks_sha256"])

    def test_t14_changed_contract_breaks_the_old_manifest(self) -> None:
        manifest = load_manifest()
        tasks = load_tasks()
        splits = load_splits()
        seeds = load_seeds()
        self.assertNotEqual(sha256_text(SCORING_CONTRACT + "\nchanged"), manifest["scoring_contract_sha256"])
        self.assertNotEqual(sha256_text(CHECKPOINT_CONTRACT + "\nchanged"), manifest["checkpoint_contract_sha256"])
        altered = dict(manifest)
        altered["scoring_contract_sha256"] = "0" * 64
        self.assertIn("scoring_contract", hash_problems(tasks, splits, seeds, altered))
        altered = dict(manifest)
        altered["checkpoint_contract_sha256"] = "0" * 64
        self.assertIn("checkpoint_contract", hash_problems(tasks, splits, seeds, altered))

    def test_t15_visible_payload_rejects_hidden_events(self) -> None:
        task = load_task("s1_meeting_a")
        self.assertEqual(agent_view_problems(agent_payload(task), task), [])
        leaked = agent_payload(task)
        leaked["events"] = task["events"]
        self.assertTrue(agent_view_problems(leaked, task))

    def test_t16_ast_finds_static_channel_imports(self) -> None:
        root = Path(__file__).resolve().parents[2] / "agent" / "algorithms"
        self.assertEqual(scan_static_channel_imports(root), [])
        found = scan_source("def load():\n    from agent.channel import qq\n")
        self.assertEqual(len(found), 1)
        self.assertEqual(
            scan_source("import importlib\nimportlib.import_module('agent.channel.qq')\n"),
            [],
        )
        self.assertEqual(scan_source("def load():\n    channel = __import__('agent.channel')\n"), [])

    def test_catalog_files_match_the_generator(self) -> None:
        catalog = build_catalog()
        manifest = load_manifest()
        self.assertEqual(sha256_json(catalog["tasks"]), manifest["tasks_sha256"])
        self.assertEqual(sha256_json(catalog["splits"]), manifest["splits_sha256"])
        self.assertEqual(sha256_json(catalog["seeds"]), manifest["fixtures_sha256"])
        self.assertEqual(manifest["schema_version"], "statebench-v1")
        self.assertEqual(manifest["generator_seed"], "20261109")
        self.assertIn("execution", manifest)
        self.assertIsNone(manifest["execution"]["code_commit"])

    def test_audit_statuses_and_human_review_stays_pending(self) -> None:
        report = run_audit(write=False)
        self.assertEqual(report["schema_and_files"], "PASS", report["schema_problems"])
        self.assertEqual(report["reset_and_events"], "PASS", report["reset_problems"])
        self.assertEqual(report["scorer_auto"], "PASS", report["scorer_problems"])
        self.assertEqual(report["human_semantic"], "PENDING")
        self.assertTrue(report["ok"])
        self.assertTrue(report["test_duplicates"])

    def test_missing_usage_stays_null(self) -> None:
        self.assertEqual(interpret_usage(None), (None, "absent"))
        self.assertEqual(interpret_usage({}), (None, "absent"))
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self.assertEqual(interpret_usage(usage), (usage, "provider"))


if __name__ == "__main__":
    unittest.main()
