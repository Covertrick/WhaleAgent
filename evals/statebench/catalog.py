"""40 个蓝图 × 2 个变体。变体只改时间、房间、版本和无关文件名。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from evals.statebench.contracts import (
    CHECKPOINT_NAME,
    MANIFEST_SCHEMA,
    checkpoint_contract_sha256,
    scoring_contract_sha256,
)
from evals.statebench.hashing import sha256_json

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
SCENARIOS = ROOT / "scenarios"
SEED_DIR = SCENARIOS / "seed"
TASKS_PATH = SCENARIOS / "tasks.json"
SPLITS_PATH = SCENARIOS / "splits.json"
MANIFEST_PATH = ROOT / "frozen_manifest.json"
GENERATOR_SEED = "20261109"

SCENES = ("S0", "S1", "S2", "S3")
VARIANTS = ("a", "b")
STRUCT_FIELDS = (
    "family_id",
    "domain",
    "goal_structure",
    "dependency_structure",
    "event_type",
    "constraint_type",
)
EVENT_TYPES = {
    "S0": "none",
    "S1": "source_notified",
    "S2": "unrelated_notified",
    "S3": "source_silent",
}
SEED_IDS = (
    "s0_meeting_a",
    "s0_note_a",
    "s1_meeting_a",
    "s1_note_a",
    "s2_meeting_a",
    "s2_note_a",
    "s3_meeting_a",
    "s3_note_a",
)

DOMAINS: dict[str, dict[str, Any]] = {
    "meeting": {
        "source_key": "meeting.time",
        "target_key": "reminder.time",
        "unrelated_key": "attachment.name",
        "room_key": "meeting.room",
        "variants": {
            "a": {
                "old": "15:00",
                "new": "16:00",
                "v_old": "v1",
                "v_new": "v2",
                "file": "slides.pdf",
                "file_new": "appendix.pdf",
                "room": "Room-A",
            },
            "b": {
                "old": "09:30",
                "new": "11:00",
                "v_old": "v3",
                "v_new": "v4",
                "file": "notes.pdf",
                "file_new": "notes-final.pdf",
                "room": "Room-B",
            },
        },
    },
    "note": {
        "source_key": "note.status",
        "target_key": "note.saved_status",
        "unrelated_key": "note.tag",
        "room_key": "note.folder",
        "variants": {
            "a": {
                "old": "draft",
                "new": "final",
                "v_old": "v1",
                "v_new": "v2",
                "file": "alpha",
                "file_new": "beta",
                "room": "Folder-A",
            },
            "b": {
                "old": "open",
                "new": "closed",
                "v_old": "v3",
                "v_new": "v4",
                "file": "gamma",
                "file_new": "delta",
                "room": "Folder-B",
            },
        },
    },
    "file": {
        "source_key": "file.status",
        "target_key": "archive.status",
        "unrelated_key": "file.owner",
        "room_key": "file.bucket",
        "variants": {
            "a": {
                "old": "pending",
                "new": "ready",
                "v_old": "v1",
                "v_new": "v2",
                "file": "alice",
                "file_new": "carol",
                "room": "Bucket-A",
            },
            "b": {
                "old": "inbox",
                "new": "stored",
                "v_old": "v3",
                "v_new": "v4",
                "file": "bob",
                "file_new": "dave",
                "room": "Bucket-B",
            },
        },
    },
    "cross": {
        "source_key": "meeting.time",
        "target_key": "note.meeting_time",
        "unrelated_key": "note.tag",
        "room_key": "meeting.room",
        "variants": {
            "a": {
                "old": "15:00",
                "new": "16:00",
                "v_old": "v1",
                "v_new": "v2",
                "file": "weekly",
                "file_new": "monthly",
                "room": "Room-A",
            },
            "b": {
                "old": "13:00",
                "new": "18:00",
                "v_old": "v3",
                "v_new": "v4",
                "file": "daily",
                "file_new": "yearly",
                "room": "Room-C",
            },
        },
    },
}


def domain_for(slot: int) -> str:
    return ("meeting", "note", "file", "cross")[slot % 4]


def split_for(slot: int) -> str:
    if slot <= 2:
        return "dev"
    if slot <= 4:
        return "val"
    return "test"


def make_task_id(scene: str, domain: str, slot: int, variant: str) -> str:
    scene_l = scene.lower()
    if domain == "meeting" and slot == 0:
        return f"{scene_l}_meeting_{variant}"
    if domain == "note" and slot == 1:
        return f"{scene_l}_note_{variant}"
    return f"{scene_l}_{domain}_{slot}{variant}"


def make_prompt(source_key: str, target_key: str) -> str:
    return (
        f"来源事实 {source_key} 。写入目标 {target_key} 。"
        "请先读取来源，再在下一轮把读到的值写入目标。"
    )


def build_task(scene: str, slot: int, variant: str) -> dict[str, Any]:
    domain = domain_for(slot)
    spec = DOMAINS[domain]
    values = spec["variants"][variant]
    event_type = EVENT_TYPES[scene]
    source_key = spec["source_key"]
    target_key = spec["target_key"]
    unrelated_key = spec["unrelated_key"]
    room_key = spec["room_key"]
    events: list[dict[str, Any]] = []
    if scene == "S1":
        events.append(
            {
                "checkpoint": CHECKPOINT_NAME,
                "fact_key": source_key,
                "value": values["new"],
                "version": values["v_new"],
                "notify": True,
            }
        )
    elif scene == "S2":
        events.append(
            {
                "checkpoint": CHECKPOINT_NAME,
                "fact_key": unrelated_key,
                "value": values["file_new"],
                "version": "v2",
                "notify": True,
            }
        )
    elif scene == "S3":
        events.append(
            {
                "checkpoint": CHECKPOINT_NAME,
                "fact_key": source_key,
                "value": values["new"],
                "version": values["v_new"],
                "notify": False,
            }
        )
    return {
        "task_id": make_task_id(scene, domain, slot, variant),
        "blueprint_id": f"bp_{scene.lower()}_{domain}_{slot}",
        "variant": variant,
        "scene": scene,
        "family_id": f"{domain}:{event_type}",
        "domain": domain,
        "goal_structure": "copy_final_source_to_target",
        "dependency_structure": "read_then_write",
        "event_type": event_type,
        "constraint_type": "single_target",
        "source_key": source_key,
        "target_key": target_key,
        "readable": [source_key, unrelated_key, room_key],
        "writable": [target_key],
        "env_only": [source_key, unrelated_key, room_key],
        "initial_facts": [
            {"key": source_key, "value": values["old"], "version": values["v_old"]},
            {"key": unrelated_key, "value": values["file"], "version": "v1"},
            {"key": room_key, "value": values["room"], "version": "v1"},
        ],
        "events": events,
        "checkpoint": CHECKPOINT_NAME,
        "success": [{"type": "equals_fact", "left": target_key, "right": source_key}],
        "constraints": [{"type": "count_equals", "key": target_key, "count": 1}],
        "prompt": make_prompt(source_key, target_key),
    }


def build_catalog() -> dict[str, Any]:
    tasks = [
        build_task(scene, slot, variant)
        for scene in SCENES
        for slot in range(10)
        for variant in VARIANTS
    ]
    splits = {"dev": [], "val": [], "test": []}
    for task in tasks:
        slot = int(task["blueprint_id"].rsplit("_", 1)[1])
        splits[split_for(slot)].append(task["task_id"])
    seeds = [task for task in tasks if task["task_id"] in SEED_IDS]
    seeds.sort(key=lambda item: SEED_IDS.index(item["task_id"]))
    return {"tasks": tasks, "splits": splits, "seeds": seeds}


def agent_payload(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": task["task_id"],
        "prompt": task["prompt"],
        "readable": list(task["readable"]),
        "writable": list(task["writable"]),
    }


def structure_key(task: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(task[field]) for field in STRUCT_FIELDS)


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_catalog() -> dict[str, Any]:
    catalog = build_catalog()
    _dump(TASKS_PATH, catalog["tasks"])
    _dump(SPLITS_PATH, catalog["splits"])
    if SEED_DIR.exists():
        for child in SEED_DIR.glob("*.json"):
            child.unlink()
    for task in catalog["seeds"]:
        _dump(SEED_DIR / f"{task['task_id']}.json", task)
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "tasks_sha256": sha256_json(catalog["tasks"]),
        "splits_sha256": sha256_json(catalog["splits"]),
        "fixtures_sha256": sha256_json(catalog["seeds"]),
        "scoring_contract_sha256": scoring_contract_sha256(),
        "checkpoint_contract_sha256": checkpoint_contract_sha256(),
        "generator_seed": GENERATOR_SEED,
        "git_commit": git_commit(),
        "execution": {
            "code_commit": None,
            "model_config": None,
            "prompt_sha256": None,
        },
    }
    _dump(MANIFEST_PATH, manifest)
    return manifest


def load_tasks() -> list[dict[str, Any]]:
    return json.loads(TASKS_PATH.read_text(encoding="utf-8"))


def load_splits() -> dict[str, list[str]]:
    return json.loads(SPLITS_PATH.read_text(encoding="utf-8"))


def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def load_seeds() -> list[dict[str, Any]]:
    seeds = []
    for task_id in SEED_IDS:
        seeds.append(json.loads((SEED_DIR / f"{task_id}.json").read_text(encoding="utf-8")))
    return seeds


def load_task(task_id: str) -> dict[str, Any]:
    for task in load_tasks():
        if task["task_id"] == task_id:
            return task
    raise KeyError(task_id)


def main() -> None:
    manifest = write_catalog()
    print(manifest["git_commit"])
    print(manifest["tasks_sha256"])


if __name__ == "__main__":
    main()
