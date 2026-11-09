"""SQLite 是权威状态，files/ 是可重建镜像。测试使用独立临时目录。"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HiddenEvent:
    checkpoint: str
    fact_key: str
    value: Any
    version: str
    notify: bool


def _events_from(items: list[Any] | None) -> list[HiddenEvent]:
    events: list[HiddenEvent] = []
    for item in items or []:
        if isinstance(item, HiddenEvent):
            events.append(item)
            continue
        events.append(
            HiddenEvent(
                checkpoint=str(item["checkpoint"]),
                fact_key=str(item["fact_key"]),
                value=item["value"],
                version=str(item["version"]),
                notify=bool(item.get("notify", True)),
            )
        )
    return events


def _facts_from(facts: dict[str, dict[str, Any]] | list[dict[str, Any]]) -> list[dict[str, str]]:
    if isinstance(facts, dict):
        rows = [
            {"key": key, "value": str(item["value"]), "version": str(item["version"])}
            for key, item in facts.items()
        ]
    else:
        rows = [
            {"key": str(item["key"]), "value": str(item["value"]), "version": str(item["version"])}
            for item in facts
        ]
    return rows


class Environment:
    def __init__(
        self,
        facts: dict[str, dict[str, Any]] | list[dict[str, Any]],
        events: list[Any] | None = None,
        root: str | Path | None = None,
        *,
        readable: list[str] | None = None,
        writable: list[str] | None = None,
        env_only: list[str] | None = None,
    ) -> None:
        self._initial = _facts_from(facts)
        self._events = _events_from(events)
        self.events = list(self._events)
        keys = {item["key"] for item in self._initial}
        self.readable = set(readable) if readable is not None else set(keys)
        self.writable = set(writable) if writable is not None else set(keys)
        self.env_only = set(env_only or [])
        self._temp: tempfile.TemporaryDirectory[str] | None = None
        if root is None:
            self._temp = tempfile.TemporaryDirectory(prefix="statebench-world-")
            self.root = Path(self._temp.name)
        else:
            self.root = Path(root)
            self.root.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self.inconsistent = False
        self.inconsistent_error = ""
        self.write_counts: dict[str, int] = {}
        self.rejected: list[dict[str, str]] = []
        self.illegal_committed = 0
        self.checkpoint_reached = False
        self._applied: set[int] = set()
        self.reset()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        temporary = self._temp
        self._temp = None
        if temporary is not None:
            try:
                temporary.cleanup()
            except Exception:
                pass

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def reset(self) -> None:
        """关闭连接，清空目录，从初始数据重建并重新打开，然后做一致性校验。"""
        self.close()
        if self.root.exists():
            for child in self.root.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        else:
            self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "files").mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.root / "world.sqlite")
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            "CREATE TABLE facts (fact_key TEXT PRIMARY KEY, value TEXT NOT NULL, version TEXT NOT NULL)"
        )
        for item in self._initial:
            self._conn.execute(
                "INSERT INTO facts(fact_key, value, version) VALUES (?, ?, ?)",
                (item["key"], item["value"], item["version"]),
            )
        self._conn.commit()
        for item in self._initial:
            self._replace_mirror(item["key"], item["value"], item["version"])
        self.inconsistent = False
        self.inconsistent_error = ""
        self.write_counts = {}
        self.rejected = []
        self.illegal_committed = 0
        self.checkpoint_reached = False
        self._applied = set()
        errors = self.consistency_errors()
        if errors:
            self.inconsistent = True
            self.inconsistent_error = "; ".join(errors)
            raise RuntimeError(self.inconsistent_error)

    def _mirror_path(self, key: str) -> Path:
        # 路径只用事实键的哈希，禁止把键拼进相对路径。
        name = hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json"
        return self.root / "files" / name

    def _replace_mirror(self, key: str, value: str, version: str) -> None:
        path = self._mirror_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"value": value, "version": version},
            ensure_ascii=False,
            sort_keys=True,
        )
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(payload + "\n", encoding="utf-8", newline="\n")
        temporary.replace(path)

    def _upsert(self, key: str, value: str, version: str) -> None:
        if self._conn is None:
            raise RuntimeError("world is closed")
        self._conn.execute(
            """
            INSERT INTO facts(fact_key, value, version) VALUES (?, ?, ?)
            ON CONFLICT(fact_key) DO UPDATE SET
                value = excluded.value,
                version = excluded.version
            """,
            (key, value, version),
        )
        self._conn.commit()
        try:
            self._replace_mirror(key, value, version)
        except Exception as exc:
            self.inconsistent = True
            self.inconsistent_error = str(exc)
            raise

    def consistency_errors(self) -> list[str]:
        if self._conn is None:
            return ["closed"]
        errors: list[str] = []
        rows = list(self._conn.execute("SELECT fact_key, value, version FROM facts"))
        names = set()
        for row in rows:
            path = self._mirror_path(row["fact_key"])
            names.add(path.name)
            if not path.is_file():
                errors.append(f"missing mirror {row['fact_key']}")
                continue
            text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                errors.append(f"bad mirror {row['fact_key']}")
                continue
            if data.get("value") != row["value"] or data.get("version") != row["version"]:
                errors.append(f"mismatch {row['fact_key']}")
        files_dir = self.root / "files"
        if files_dir.exists():
            for path in files_dir.iterdir():
                if path.is_file() and path.suffix != ".tmp" and path.name not in names:
                    errors.append(f"extra {path.name}")
        return errors

    def get(self, key: str) -> dict[str, str] | None:
        if self._conn is None:
            raise RuntimeError("world is closed")
        row = self._conn.execute(
            "SELECT value, version FROM facts WHERE fact_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return {"value": row["value"], "version": row["version"]}

    @property
    def truth(self) -> dict[str, dict[str, str]]:
        if self._conn is None:
            raise RuntimeError("world is closed")
        rows = self._conn.execute("SELECT fact_key, value, version FROM facts")
        return {
            row["fact_key"]: {"value": row["value"], "version": row["version"]}
            for row in rows
        }

    def logical_hash(self) -> str:
        """对排序后的事实和镜像内容做规范 JSON，再 SHA256。不对 SQLite 文件字节哈希。"""
        facts = [
            {"key": key, "value": item["value"], "version": item["version"]}
            for key, item in sorted(self.truth.items())
        ]
        files: list[dict[str, str]] = []
        files_dir = self.root / "files"
        if files_dir.exists():
            for path in sorted(item for item in files_dir.rglob("*") if item.is_file()):
                files.append(
                    {
                        "path": path.relative_to(self.root).as_posix(),
                        "content": path.read_text(encoding="utf-8").replace("\r\n", "\n"),
                    }
                )
        payload = json.dumps(
            {"facts": facts, "files": files},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def snapshot_token(self) -> str:
        return self.logical_hash()

    def apply_checkpoint(self, name: str) -> list[str]:
        """写入真值。只有 notify 的事实键会返回给 Agent。"""
        notified: list[str] = []
        for index, event in enumerate(self._events):
            if index in self._applied or event.checkpoint != name:
                continue
            self._upsert(event.fact_key, str(event.value), str(event.version))
            self._applied.add(index)
            if event.notify:
                notified.append(event.fact_key)
        self.checkpoint_reached = True
        return notified

    def observe(self, fact_keys: list[str] | tuple[str, ...]) -> dict[str, dict[str, str]]:
        found: dict[str, dict[str, str]] = {}
        for key in fact_keys:
            row = self.get(key)
            if row is None:
                found[key] = {"error": "missing_key", "fact_key": key}
            else:
                found[key] = dict(row)
        return found

    def agent_read(self, key: str) -> dict[str, Any]:
        if key not in self.readable and key not in self.writable:
            return {"ok": False, "error": "not_readable", "fact_key": key}
        row = self.get(key)
        if row is None:
            return {"ok": False, "error": "missing_key", "fact_key": key}
        return {"ok": True, "fact_key": key, "value": row["value"], "version": row["version"]}

    def agent_write(self, key: str, value: str) -> dict[str, Any]:
        if key not in self.writable or key in self.env_only:
            self.rejected.append({"fact_key": key, "value": str(value), "reason": "not_writable"})
            return {"ok": False, "error": "not_writable", "fact_key": key}
        current = self.get(key)
        if current is None:
            version = "v1"
        elif current["version"].startswith("v") and current["version"][1:].isdigit():
            version = f"v{int(current['version'][1:]) + 1}"
        else:
            version = "v1"
        self._upsert(key, str(value), version)
        self.write_counts[key] = self.write_counts.get(key, 0) + 1
        return {"ok": True, "fact_key": key, "value": str(value), "version": version}
