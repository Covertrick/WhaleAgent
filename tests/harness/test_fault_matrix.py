"""故障矩阵。20 个种子只改变编号，不改变判定。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.algorithms.types import BeliefState, Evidence, PlanNode
from agent.application.conditional_write import WritePreconditions, judge_write
from agent.core.phase_usage import usage_from_api
from agent.policies.egaa import EGAAPolicy
from agent.vault.writer import write_draft_note
from evals.statebench.reliability import run_matrix, summarize


class FaultMatrixTests(unittest.TestCase):
    def test_two_hundred_seeds_have_no_unsafe_effect(self) -> None:
        rows = run_matrix()
        report = summarize(rows)
        self.assertEqual(report["scenarios"], 200)
        self.assertEqual(report["duplicate_irreversible"], 0)
        self.assertEqual(report["unauthorized_writes"], 0)
        self.assertEqual(report["stale_commits"], 0)
        self.assertEqual(report["false_success"], 0)
        required = [row for row in rows if row.fault in {"F04", "F05", "F06", "F07", "F09", "F10"}]
        self.assertTrue(all(row.unknown_preserved for row in required))
        self.assertEqual(report["residual_races"], 20)

    def test_same_store_rejects_a_moved_target(self) -> None:
        verdict = judge_write(
            WritePreconditions(
                expected_source_revision="v1",
                observed_source_revision="v1",
                expected_target_revision="h1",
                observed_target_revision="h2",
                cross_system=False,
            )
        )
        self.assertEqual(verdict, "reject_target")

    def test_policy_does_not_emit_a_stale_reminder(self) -> None:
        node = PlanNode(
            "write_reminder",
            "write_fact",
            args={"fact_key": "schedule.reminder", "value_from": {"fact_key": "project.deadline"}},
            irreversible=True,
        )
        policy = EGAAPolicy([node], revision_probe=lambda _key: "v2")
        evidence = Evidence("ev1", "project.deadline", "2026-12-01T09:00:00+08:00", "vault://deadline", "v1", 1, "VALID")
        policy.belief = BeliefState(evidence={"ev1": evidence}, slots={"project.deadline": "ev1"})
        decision = policy._revision_block(node, "schedule.reminder")
        assert decision is not None
        self.assertEqual(decision.reason_codes, ("REVISION_CONFLICT",))

    def test_missing_usage_stays_null(self) -> None:
        row = usage_from_api({}, phase="plan")
        self.assertEqual(row.phase, "plan_generate")
        self.assertIsNone(row.prompt_tokens)
        self.assertIsNone(row.completion_tokens)
        self.assertIsNone(row.cached_tokens)

    def test_vault_refuses_a_moved_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            import agent.vault.sync as sync
            from agent.config import VAULT_NOTES_SUBDIR
            from datetime import datetime

            old = sync.VAULT_PATH
            sync.VAULT_PATH = tmp
            try:
                path = Path(tmp) / VAULT_NOTES_SUBDIR
                path.mkdir()
                day = datetime.now().strftime("%Y-%m-%d")
                target = path / f"{day}-项目待办草稿-draft.md"
                target.write_text("旧正文", encoding="utf-8")
                import hashlib

                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                moved = write_draft_note("项目待办草稿", "新正文", expected_content_sha256="0" * 64)
                self.assertIn("已经变化", moved)
                self.assertEqual(target.read_text(encoding="utf-8"), "旧正文")
                same = write_draft_note("项目待办草稿", "新正文", expected_content_sha256=digest)
                self.assertIn("未再次写入", same)
                self.assertEqual(target.read_text(encoding="utf-8"), "旧正文")
            finally:
                sync.VAULT_PATH = old
