"""固定故障种子。不调用模型。每种故障 20 个种子，用来检查副作用语义。"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import agent.config as cfg
from agent.application.conditional_write import WritePreconditions, judge_write
from agent.application.effects import effect_status
from agent.harness.adapters import HarnessExecutorAdapter
from agent.harness.effect import IntentStatus, RunStatus
from agent.harness.runtime import HarnessRuntime, _current
from agent.harness.store import HarnessStore
from agent.schedules.store import ScheduleStore

SEEDS = tuple(range(20))
FAULTS = tuple(f"F{index:02d}" for index in range(1, 11))
GUARD = "不可逆结果未知时禁止自动重试"


@dataclass
class FaultResult:
    fault: str
    seed: int
    irreversible_writes: int = 0
    unauthorized_writes: int = 0
    stale_commits: int = 0
    false_success: int = 0
    unknown_preserved: bool = True
    residual_races: int = 0
    notes: list[str] = field(default_factory=list)


def run_matrix() -> list[FaultResult]:
    rows: list[FaultResult] = []
    for fault in FAULTS:
        for seed in SEEDS:
            rows.append(_run(fault, seed))
    return rows


def summarize(rows: list[FaultResult]) -> dict:
    return {
        "scenarios": len(rows),
        "duplicate_irreversible": sum(1 for row in rows if row.irreversible_writes > 1),
        "unauthorized_writes": sum(row.unauthorized_writes for row in rows),
        "stale_commits": sum(row.stale_commits for row in rows),
        "false_success": sum(row.false_success for row in rows),
        "unknown_preserved": sum(1 for row in rows if row.unknown_preserved),
        "unknown_required": sum(1 for row in rows if row.fault in {"F04", "F05", "F06", "F07", "F09", "F10"}),
        "residual_races": sum(row.residual_races for row in rows),
    }


def _run(fault: str, seed: int) -> FaultResult:
    if fault == "F01":
        return _version_case(fault, seed, observed="v1", window=False, cross=False)
    if fault == "F02":
        return _version_case(fault, seed, observed="v2", window=False, cross=False)
    if fault == "F03":
        return _version_case(fault, seed, observed="v1", window=True, cross=True)
    if fault == "F08":
        return _same_operation_id(seed)
    return _harness_case(fault, seed)


def _version_case(fault: str, seed: int, *, observed: str, window: bool, cross: bool) -> FaultResult:
    verdict = judge_write(
        WritePreconditions(
            expected_source_revision="v1",
            observed_source_revision=observed,
            expected_target_revision="t1",
            observed_target_revision="t1",
            cross_system=cross,
            commit_window_changed=window,
        )
    )
    row = FaultResult(fault, seed)
    committed = verdict == "commit"
    row.irreversible_writes = 1 if committed else 0
    row.stale_commits = 1 if committed and (observed != "v1" or window) else 0
    row.residual_races = 1 if verdict == "residual_race" else 0
    row.unknown_preserved = True
    row.notes.append(verdict)
    return row


def _same_operation_id(seed: int) -> FaultResult:
    row = FaultResult("F08", seed)
    with tempfile.TemporaryDirectory() as tmp:
        store = ScheduleStore(Path(tmp) / "sched.db")
        operation_id = f"op-{seed}"
        first, _ticks = store.create_task_with_reminders(
            user_id=str(seed),
            group_id="private",
            title=f"截止 {seed}",
            due_at="2026-12-01T09:00:00+08:00",
            operation_id=operation_id,
        )
        second, extra = store.create_task_with_reminders(
            user_id=str(seed),
            group_id="private",
            title=f"截止 {seed} 另一条",
            due_at="2026-12-02T09:00:00+08:00",
            operation_id=operation_id,
        )
        row.irreversible_writes = 1 if first.id == second.id and extra == [] else 2
        row.false_success = 0 if first.id == second.id else 1
    return row


def _rebind(runtime: HarnessRuntime) -> None:
    """崩溃之后用落盘的 Run，不用内存里还停在 STARTED 的那一份。"""
    _current.set(None)
    runs = runtime.store.list_runs()
    if runs:
        _current.set(runs[-1])


def _harness_case(fault: str, seed: int) -> FaultResult:
    row = FaultResult(fault, seed)
    with tempfile.TemporaryDirectory() as tmp:
        old = cfg.QQ_RUNTIME
        cfg.QQ_RUNTIME = tmp
        _current.set(None)
        try:
            runtime = HarnessRuntime(HarnessStore())
            calls: list[str] = []

            def schedule_reminder(title: str, due_at: str, category: str = "todo", operation_id: str = "") -> str:
                _ = (title, due_at, category)
                calls.append(operation_id)
                if fault == "F06":
                    return "created"
                return "UNKNOWN: timeout"

            adapter = HarnessExecutorAdapter({"schedule_reminder": schedule_reminder})
            run = runtime.start_run(channel="qq", user_id=f"{fault}-{seed}", group_id=None, text="提醒")
            run.guardrail_text = GUARD
            runtime.store.save(run)
            args = {"title": f"截止 {seed}", "due_at": "2026-12-01T09:00:00+08:00", "category": "todo"}
            if fault == "F05":
                runtime.begin_intent(run, "schedule_reminder", args)
                HarnessRuntime(runtime.store).recover_open_runs()
                _rebind(runtime)
                adapter.execute("schedule_reminder", args)
            elif fault == "F06":
                begun = runtime.begin_intent(run, "schedule_reminder", args)
                schedule_reminder(args["title"], args["due_at"], operation_id=begun.intent_id)
                HarnessRuntime(runtime.store).recover_open_runs()
                _rebind(runtime)
                adapter.execute("schedule_reminder", args)
            else:
                adapter.execute("schedule_reminder", args)
                if fault != "F09":
                    adapter.execute("schedule_reminder", args)
            if fault == "F09":
                runtime.begin_intent(run, "schedule_reminder", args)
                restarted = HarnessRuntime(runtime.store)
                restarted.recover_open_runs()
                again = restarted.recover_open_runs()
                row.notes.append(f"second_recovery={len(again)}")
            loaded = runtime.store.load(run.run_id)
            assert loaded is not None
            row.irreversible_writes = len(calls)
            if fault in {"F04", "F05", "F06", "F07", "F10"}:
                unknown = any(item.status == IntentStatus.UNKNOWN.value for item in loaded.intents)
                row.unknown_preserved = unknown and loaded.status == RunStatus.UNKNOWN.value
            if fault == "F07":
                listed = f"项目截止 | operation_id=other-{seed}"
                intent_id = loaded.intents[0].intent_id
                if intent_id in listed:
                    row.false_success = 1
            if fault == "F10":
                query = "Error: network"
                if effect_status(query) == "CONFIRMED":
                    row.false_success = 1
                if loaded.intents[0].status != IntentStatus.UNKNOWN.value:
                    row.unknown_preserved = False
            if fault == "F01":
                pass
        finally:
            _current.set(None)
            cfg.QQ_RUNTIME = old
    return row
