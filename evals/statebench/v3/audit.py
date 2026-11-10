"""StateBench v3 自动审计。语义复核由开发者完成，不是第三方。"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from evals.statebench.v3.catalog import SPECS, all_tasks
from evals.statebench.v3.semantic_review import apply_review
from evals.statebench.v3.world import initial_hash, logic_hash, play, score, visible_task

ROOT = Path(__file__).resolve().parent
LEGACY = {
    "v2_live_results.json": "be6273ed22bc1d6d6a44b1428f654d2dc64dd8d4b68407ba1d6e021578bc738c",
    "v2_dev_after.json": "e130fe27ca17ed5bb1daa38837ce17b93d03092c97d55ca477b3a7fdf7abfaec",
    "v2_heldout_results.json": "d3a0519e4210a0543833186130bac46473e72cf8edc196f108e3cd141a89415f",
    "v2_heldout_frozen.json": "8ce7abda2af2eb5f6f521a2aca8603c7ef8f9562fb6e07b6454b1cd398366f83",
    "v2_heldout_tasks.json": "cb323e6b492c6e72095ac0e3a6a97bd5cde85daf36d9a198f5ee9d27b6270e9c",
    "d14_report.md": "70a041d160f48898fffcef4a40264bb66f7ab52b653c5ba126d29c786b246f0d",
    "frozen_manifest.json": "74cd433c9416dca5be5dd445b32f25bb54ed2397807f43776605026549ff9e59",
    "frozen_config.json": "d1a208724a2bfd29f2a32b1579c764dfe492269163c89126a0eb48c909976bef",
}


def _legacy_ok() -> tuple[bool, str]:
    root = ROOT.parent
    for name, expect in LEGACY.items():
        path = root / name
        if not path.exists():
            return False, name + " missing"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expect:
            return False, name + " changed"
    return True, ""


def _hidden_in_prompt(task: dict) -> str:
    for source in task["sources"]:
        if source["v1"] == source["v2"]:
            continue
        for secret in (source["phrase"], source["detail"], source["token_v2"]):
            if secret and secret not in source["v1"] and secret in task["prompt"]:
                return secret
    return ""


def _event_ok(task: dict) -> bool:
    world_a = play(task, "correct")
    world_b = play(task, "correct")
    if task["change_on"] == "never":
        return world_a.checkpoint_reached is False and [item["text"] for item in world_a.docs.values()] == [
            item["v1"] for item in task["sources"]
        ]
    changed = [item for item in task["sources"] if item["v1"] != item["v2"]]
    if not changed or not world_b.checkpoint_reached:
        return False
    sample = changed[0]
    probe = __import__("evals.statebench.v3.world", fromlist=["World"]).World(task)
    first = probe.read(sample["sid"])
    second = probe.read(sample["sid"])
    return first["content"] == sample["v1"] and second["content"] == sample["v2"]


def _score_ok(task: dict) -> tuple[bool, str]:
    correct = score(task, play(task, "correct"))
    wrong = score(task, play(task, "wrong"))
    safe = score(task, play(task, "safe"))
    exact = any(item["reminder_mode"] == "exact" for item in task["writes"])
    if not correct["success"] or wrong["success"]:
        return False, "correct/wrong"
    if exact and safe["success"]:
        return False, "safe looked successful"
    if not exact and not safe["success"]:
        return False, "safe stop rejected"
    if exact and safe["failure_reasons"] == wrong["failure_reasons"]:
        return False, "safe and wrong collapsed"
    return True, ""


def audit_rows() -> list[dict]:
    tasks = all_tasks()
    by_blueprint: dict[str, list[dict]] = {}
    for task in tasks:
        by_blueprint.setdefault(task["blueprint_id"], []).append(task)
    splits: dict[str, set[str]] = {"dev": set(), "val": set(), "test": set()}
    for spec in SPECS:
        splits[spec.split].add(spec.blueprint_id)
    overlap = splits["dev"] & splits["val"] or splits["dev"] & splits["test"] or splits["val"] & splits["test"]
    legacy_ok, legacy_note = _legacy_ok()
    rows = []
    for task in tasks:
        pair = by_blueprint[task["blueprint_id"]]
        same_rule = pair[0]["writes"] == pair[1]["writes"] and pair[0]["change_on"] == pair[1]["change_on"]
        required = ("task_id", "blueprint_id", "public_goal", "sources", "writes", "allowed_tools")
        schema_ok = all(task.get(key) not in (None, "", []) for key in required)
        reset_ok = initial_hash(task) == initial_hash(task)
        leaked = _hidden_in_prompt(task)
        score_ok, score_note = _score_ok(task)
        event_ok = _event_ok(task)
        notes = []
        if not schema_ok:
            notes.append("schema")
        if not reset_ok:
            notes.append("reset")
        if not event_ok:
            notes.append("event")
        if not score_ok:
            notes.append(score_note)
        if not same_rule:
            notes.append("variant")
        if overlap:
            notes.append("split")
        if leaked:
            notes.append("leak:" + leaked)
        if not legacy_ok:
            notes.append(legacy_note)
        if not task["goal_structure"] or not task["writes"]:
            notes.append("goal")
        rows.append(
            {
                "task_id": task["task_id"],
                "blueprint_id": task["blueprint_id"],
                "split": task["split"],
                "schema_ok": schema_ok,
                "reset_ok": reset_ok,
                "hash_stable": reset_ok,
                "logic_hash": logic_hash(task),
                "event_ok": event_ok,
                "scorer_ok": score_ok,
                "variant_same_rule": same_rule,
                "split_disjoint": not overlap,
                "no_leak": not leaked,
                "legacy_unchanged": legacy_ok,
                "goal_defined": bool(task["goal_structure"] and task["writes"]),
                "human_review": "HUMAN_REVIEW_PENDING",
                "reviewer": "developer",
                "third_party": "no",
                "review_note": "",
                "notes": ";".join(notes),
            }
        )
        apply_review(rows[-1], task)
    return rows


def write_outputs() -> dict:
    rows = audit_rows()
    splits = {"dev": [], "val": [], "test": []}
    for spec in SPECS:
        splits[spec.split].append(spec.blueprint_id)
    (ROOT / "splits.json").write_text(json.dumps(splits, ensure_ascii=False, indent=2), encoding="utf-8")
    public = ROOT / "fixtures" / "public"
    private = ROOT / "fixtures" / "private"
    public.mkdir(parents=True, exist_ok=True)
    private.mkdir(parents=True, exist_ok=True)
    for task in all_tasks():
        view = visible_task(
            {
                "task_id": task["task_id"],
                "public_goal": task["public_goal"],
                "titles": task["titles"],
                "allowed_tools": task["allowed_tools"],
            }
        )
        (public / f"{task['task_id']}.json").write_text(json.dumps(view, ensure_ascii=False, indent=2), encoding="utf-8")
        hidden = {
            "task_id": task["task_id"],
            "sources": task["sources"],
            "writes": task["writes"],
            "change_on": task["change_on"],
            "notify": task["notify"],
            "goal_structure": task["goal_structure"],
        }
        (private / f"{task['task_id']}.json").write_text(json.dumps(hidden, ensure_ascii=False, indent=2), encoding="utf-8")
    fieldnames = list(rows[0])
    with (ROOT / "reviewer_audit.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    failed = [row["task_id"] for row in rows if row["notes"]]
    return {
        "tasks": len(rows),
        "blueprints": len(SPECS),
        "automated_failures": failed,
        "human_review": "developer_reviewed" if not failed else "HUMAN_REVIEW_PENDING",
        "third_party": "no",
    }


def main() -> None:
    report = write_outputs()
    print(json.dumps(report, ensure_ascii=False))
    if report["automated_failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
