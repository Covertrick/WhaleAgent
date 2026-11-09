"""双轨迹。Agent 可见记录不写隐藏事件和写入当时的真值版本。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.statebench.contracts import TRACE_SCHEMA


class TraceWriter:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.agent_path = self.directory / "agent_trace.jsonl"
        self.visible_path = self.directory / "trace.jsonl"
        self.world_path = self.directory / "world_trace.jsonl"
        for path in (self.agent_path, self.visible_path, self.world_path):
            path.write_text("", encoding="utf-8", newline="\n")

    def agent(self, record: dict[str, Any]) -> None:
        self._append(self.agent_path, record)
        self._append(self.visible_path, record)

    def world(self, record: dict[str, Any]) -> None:
        self._append(self.world_path, record)

    def _append(self, path: Path, record: dict[str, Any]) -> None:
        line = json.dumps({"schema": TRACE_SCHEMA, **record}, ensure_ascii=False)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    text = Path(path).read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows
