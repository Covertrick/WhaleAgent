"""冻结清单审计。前三项必须通过，人工语义复核保持 PENDING。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from evals.statebench.catalog import (
    GENERATOR_SEED,
    SEED_IDS,
    STRUCT_FIELDS,
    agent_payload,
    load_manifest,
    load_seeds,
    load_splits,
    load_tasks,
    structure_key,
)
from evals.statebench.contracts import CHECKPOINT_NAME, MANIFEST_SCHEMA
from evals.statebench.environment import Environment, HiddenEvent
from evals.statebench.episode import state_change_notice
from evals.statebench.hashing import canonical_json, sha256_json
from evals.statebench.scorer import assertion_holds, score_episode

HIDDEN_FIELDS = {
    "events",
    "hidden_events",
    "success",
    "constraints",
    "expected",
    "actual_source_version_at_write",
}
AUDIT_PATH = Path(__file__).resolve().parent / "audit.md"


def hidden_fields(payload: dict[str, Any]) -> list[str]:
    return sorted(HIDDEN_FIELDS & set(payload))


def agent_view_problems(payload: dict[str, Any], task: dict[str, Any] | None = None) -> list[str]:
    problems = [f"hidden field {name}" for name in hidden_fields(payload)]
    if task is None:
        return problems
    text = json.dumps(payload, ensure_ascii=False)
    for event in task.get("events") or []:
        secret = str(event["value"])
        if secret and secret in text:
            problems.append(f"hidden value {secret}")
    return problems


def blueprint_cross_splits(tasks: list[dict[str, Any]], splits: dict[str, list[str]]) -> list[str]:
    by_id = {task["task_id"]: task["blueprint_id"] for task in tasks}
    location: dict[str, str] = {}
    problems: list[str] = []
    for name, task_ids in splits.items():
        for task_id in task_ids:
            blueprint_id = by_id[task_id]
            previous = location.get(blueprint_id)
            if previous is not None and previous != name:
                problems.append(blueprint_id)
            location[blueprint_id] = name
    return sorted(set(problems))


def structural_duplicates(
    tasks: list[dict[str, Any]],
    task_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[str]] = {}
    seen: set[str] = set()
    for task in tasks:
        if task_ids is not None and task["task_id"] not in task_ids:
            continue
        if task["blueprint_id"] in seen:
            continue
        seen.add(task["blueprint_id"])
        groups.setdefault(structure_key(task), []).append(task["blueprint_id"])
    duplicates = []
    for key, blueprint_ids in groups.items():
        if len(blueprint_ids) > 1:
            duplicates.append(
                {
                    "structure": dict(zip(STRUCT_FIELDS, key)),
                    "blueprint_ids": blueprint_ids,
                }
            )
    return duplicates


def hash_problems(
    tasks: list[dict[str, Any]],
    splits: dict[str, list[str]],
    seeds: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> list[str]:
    from evals.statebench.contracts import checkpoint_contract_sha256, scoring_contract_sha256

    problems = []
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        problems.append("schema_version")
    if manifest.get("generator_seed") != GENERATOR_SEED:
        problems.append("generator_seed")
    if sha256_json(tasks) != manifest.get("tasks_sha256"):
        problems.append("tasks")
    if sha256_json(splits) != manifest.get("splits_sha256"):
        problems.append("splits")
    if sha256_json(seeds) != manifest.get("fixtures_sha256"):
        problems.append("fixtures")
    if scoring_contract_sha256() != manifest.get("scoring_contract_sha256"):
        problems.append("scoring_contract")
    if checkpoint_contract_sha256() != manifest.get("checkpoint_contract_sha256"):
        problems.append("checkpoint_contract")
    return problems


def success_problems(task: dict[str, Any]) -> list[str]:
    problems = []
    writable = set(task["writable"])
    known = {item["key"] for item in task["initial_facts"]} | writable
    for event in task.get("events") or []:
        known.add(event["fact_key"])
    task_id = task["task_id"]
    if task["source_key"] in writable:
        problems.append(f"{task_id} source writable")
    if task["target_key"] not in writable:
        problems.append(f"{task_id} target not writable")
    for condition in task["success"]:
        if condition["type"] != "equals_fact":
            problems.append(f"{task_id} unexpected success type")
            continue
        if condition["left"] not in writable:
            problems.append(f"{task_id} output not writable")
        if condition["left"] not in known or condition["right"] not in known:
            problems.append(f"{task_id} scorer cannot read success fact")
        if condition["right"] in writable:
            problems.append(f"{task_id} comparison source writable")
    return problems


def schema_problems(
    tasks: list[dict[str, Any]],
    splits: dict[str, list[str]],
    seeds: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> list[str]:
    problems = hash_problems(tasks, splits, seeds, manifest)
    if len(tasks) != 80:
        problems.append(f"task count {len(tasks)}")
    blueprints = {task["blueprint_id"] for task in tasks}
    if len(blueprints) != 40:
        problems.append(f"blueprint count {len(blueprints)}")
    expected = {"dev": 24, "val": 16, "test": 40}
    for name, count in expected.items():
        if len(splits.get(name) or []) != count:
            problems.append(f"{name} count {len(splits.get(name) or [])}")
    placed = [task_id for ids in splits.values() for task_id in ids]
    if len(placed) != len(set(placed)) or set(placed) != {task["task_id"] for task in tasks}:
        problems.append("split membership")
    problems.extend(blueprint_cross_splits(tasks, splits))
    by_blueprint: dict[str, list[str]] = {}
    for task in tasks:
        by_blueprint.setdefault(task["blueprint_id"], []).append(task["variant"])
    for blueprint_id, variants in by_blueprint.items():
        if sorted(variants) != ["a", "b"]:
            problems.append(f"{blueprint_id} variants")
    by_id = {task["task_id"]: canonical_json(task) for task in tasks}
    if [task["task_id"] for task in seeds] != list(SEED_IDS):
        problems.append("seed ids")
    for seed in seeds:
        if by_id.get(seed["task_id"]) != canonical_json(seed):
            problems.append(f"seed drift {seed['task_id']}")
    for task in tasks:
        problems.extend(
            f"{task['task_id']} {item}" for item in agent_view_problems(agent_payload(task), task)
        )
        problems.extend(success_problems(task))
        for event in task.get("events") or []:
            notice = state_change_notice(event["fact_key"])
            if str(event["value"]) in json.dumps(notice, ensure_ascii=False):
                problems.append(f"{task['task_id']} notice leaks")
    return problems


def reset_problems(seeds: list[dict[str, Any]]) -> list[str]:
    problems = []
    for task in seeds:
        try:
            with tempfile.TemporaryDirectory(prefix="statebench-audit-") as temporary:
                root = Path(temporary)
                env = None
                fresh = None
                try:
                    env = Environment(
                        task["initial_facts"],
                        task.get("events") or [],
                        root,
                        readable=task["readable"],
                        writable=task["writable"],
                        env_only=task["env_only"],
                    )
                    if env.checkpoint_reached:
                        problems.append(f"{task['task_id']} checkpoint before read")
                    initial = {item["key"]: item["value"] for item in task["initial_facts"]}
                    source = env.get(task["source_key"])
                    if source is None or source["value"] != initial[task["source_key"]]:
                        problems.append(f"{task['task_id']} changed before checkpoint")
                    token = env.snapshot_token()
                    env.reset()
                    if env.snapshot_token() != token:
                        problems.append(f"{task['task_id']} reset hash")
                    if env._conn is None:
                        raise RuntimeError("world closed")
                    env._conn.execute(
                        "UPDATE facts SET value = ? WHERE fact_key = ?",
                        ("tampered", task["source_key"]),
                    )
                    env._conn.commit()
                    env._mirror_path(task["source_key"]).write_text("tampered\n", encoding="utf-8")
                    env.reset()
                    restored = env.get(task["source_key"])
                    if env.snapshot_token() != token or restored is None:
                        problems.append(f"{task['task_id']} reset did not restore hash")
                    elif restored["value"] != initial[task["source_key"]]:
                        problems.append(f"{task['task_id']} reset did not restore value")
                    fresh = Environment(
                        task["initial_facts"],
                        task.get("events") or [],
                        root / "again",
                        readable=task["readable"],
                        writable=task["writable"],
                        env_only=task["env_only"],
                    )
                    notices = fresh.apply_checkpoint(task["checkpoint"])
                    notified = [event["fact_key"] for event in task.get("events") or [] if event["notify"]]
                    if notices != notified:
                        problems.append(f"{task['task_id']} notice keys")
                    for event in task.get("events") or []:
                        row = fresh.get(event["fact_key"])
                        if row is None or row["value"] != event["value"] or row["version"] != event["version"]:
                            problems.append(f"{task['task_id']} event not applied")
                finally:
                    if env is not None:
                        env.close()
                    if fresh is not None:
                        fresh.close()
        except Exception as exc:
            problems.append(f"{task['task_id']} reset error {exc}")
    return problems


def scorer_problems() -> list[str]:
    problems = []
    try:
        base = Environment(
            [
                {"key": "meeting.time", "value": "16:00", "version": "v2"},
                {"key": "reminder.time", "value": "16:00", "version": "v1"},
            ],
            readable=["meeting.time", "reminder.time"],
            writable=["reminder.time"],
            env_only=["meeting.time"],
        )
        base.agent_write("reminder.time", "16:00")
        checks = {
            "equals_fact": {"type": "equals_fact", "left": "reminder.time", "right": "meeting.time"},
            "equals_literal": {"type": "equals_literal", "key": "reminder.time", "value": "16:00"},
            "exists": {"type": "exists", "key": "reminder.time"},
            "count_equals": {"type": "count_equals", "key": "reminder.time", "count": 1},
        }
        for name, condition in checks.items():
            if not assertion_holds(condition, base):
                problems.append(name)
        moved = Environment(
            [{"key": "meeting.time", "value": "15:00", "version": "v1"}],
            [HiddenEvent(CHECKPOINT_NAME, "meeting.time", "16:00", "v2", True)],
            readable=["meeting.time"],
            writable=["reminder.time"],
            env_only=["meeting.time"],
        )
        observed = moved.agent_read("meeting.time")
        moved.apply_checkpoint(CHECKPOINT_NAME)
        moved.agent_write("reminder.time", observed["value"])
        literal_old = assertion_holds(
            {"type": "equals_literal", "key": "reminder.time", "value": "15:00"},
            moved,
        )
        relational = assertion_holds(
            {"type": "equals_fact", "left": "reminder.time", "right": "meeting.time"},
            moved,
        )
        if not literal_old or relational:
            problems.append("equals_fact still accepts the old literal")
        score = score_episode(
            {
                "success": [{"type": "equals_fact", "left": "reminder.time", "right": "meeting.time"}],
                "constraints": [{"type": "count_equals", "key": "reminder.time", "count": 1}],
            },
            moved,
            [
                {
                    "committed": True,
                    "provenance": "observed",
                    "source_key": "meeting.time",
                    "last_observed_source_version": observed["version"],
                    "actual_source_version_at_write": moved.get("meeting.time")["version"],
                    "written_value": observed["value"],
                }
            ],
            checkpoint_reached=True,
        )
        if score["goal_met"]:
            problems.append("stale write counted as success")
        if score["stale_source_writes"] != 1 or score["wrong_final_values"] != 1:
            problems.append("stale and wrong final value are not separate")
        if score["false_invalidations"] != "not_applicable":
            problems.append("false_invalidations without a log")
        if moved.agent_read("missing.key").get("error") != "not_readable":
            problems.append("bad key")
        moved.readable.add("missing.key")
        if moved.agent_read("missing.key").get("error") != "missing_key":
            problems.append("missing key")
        before = moved.get("meeting.time")["value"]
        rejected = moved.agent_write("meeting.time", "99:00")
        if rejected.get("ok") or moved.get("meeting.time")["value"] != before or not moved.rejected:
            problems.append("source write was committed")
        if moved.illegal_committed != 0:
            problems.append("rejected write counted as committed")
        silent = Environment(
            [{"key": "meeting.time", "value": "15:00", "version": "v1"}],
            [HiddenEvent(CHECKPOINT_NAME, "meeting.time", "16:00", "v2", False)],
        )
        if silent.apply_checkpoint(CHECKPOINT_NAME):
            problems.append("silent checkpoint returned a notice")
        if silent.get("meeting.time")["version"] != "v2":
            problems.append("silent checkpoint hid the new version from the scorer")
        base.close()
        moved.close()
        silent.close()
    except Exception as exc:
        problems.append(f"scorer error {exc}")
    return problems


def run_audit(
    *,
    tasks: list[dict[str, Any]] | None = None,
    splits: dict[str, list[str]] | None = None,
    seeds: list[dict[str, Any]] | None = None,
    manifest: dict[str, Any] | None = None,
    write: bool = False,
) -> dict[str, Any]:
    tasks = load_tasks() if tasks is None else tasks
    splits = load_splits() if splits is None else splits
    seeds = load_seeds() if seeds is None else seeds
    manifest = load_manifest() if manifest is None else manifest
    schema = schema_problems(tasks, splits, seeds, manifest)
    reset = reset_problems(seeds)
    scorer = scorer_problems()
    report = {
        "schema_and_files": "PASS" if not schema else "FAIL",
        "reset_and_events": "PASS" if not reset else "FAIL",
        "scorer_auto": "PASS" if not scorer else "FAIL",
        "human_semantic": "PENDING",
        "schema_problems": schema,
        "reset_problems": reset,
        "scorer_problems": scorer,
        "test_duplicates": structural_duplicates(tasks, set(splits.get("test") or [])),
        "ok": not schema and not reset and not scorer,
    }
    if write:
        AUDIT_PATH.write_text(render_audit(report), encoding="utf-8")
    return report


def render_audit(report: dict[str, Any]) -> str:
    lines = [
        "# StateBench 审计",
        "",
        "这 80 题是受控模板实例，不是 80 种独立任务类型。",
        "题数不表示有 80 种决策结构。下面列出冻结测试集里结构五元组完全相同的蓝图。",
        "",
        "## 状态",
        "",
        "| 项目 | 状态 |",
        "| --- | --- |",
        f"| Schema 与文件完整性 | {report['schema_and_files']} |",
        f"| 重置与事件注入 | {report['reset_and_events']} |",
        f"| 评分器自动测试 | {report['scorer_auto']} |",
        f"| 人工任务语义复核 | {report['human_semantic']} |",
        "",
        "人工任务语义复核保持 PENDING。能加载、哈希相符、自动评分通过，都不表示题意和评分已经被人工确认。",
        "",
        "## 冻结测试集中的结构重复",
        "",
    ]
    duplicates = report["test_duplicates"]
    if not duplicates:
        lines.append("冻结测试集里没有结构五元组完全相同的不同蓝图。")
    for group in duplicates:
        structure = ", ".join(f"{key}={value}" for key, value in group["structure"].items())
        joined = ", ".join(group["blueprint_ids"])
        lines.append(f"- {structure}: {joined}")
    lines.extend(["", "## 机器检查", ""])
    for label, items in (
        ("Schema", report["schema_problems"]),
        ("重置与事件", report["reset_problems"]),
        ("评分器", report["scorer_problems"]),
    ):
        if items:
            lines.append(f"{label}：")
            lines.extend(f"- {item}" for item in items)
        else:
            lines.append(f"{label}：通过。")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    report = run_audit(write=True)
    print(report["schema_and_files"], report["reset_and_events"], report["scorer_auto"], report["human_semantic"])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
