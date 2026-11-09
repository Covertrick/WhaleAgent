"""用 AST 扫静态 import。importlib / __import__ 不在这项检查里。"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ImportHit:
    file: str
    line: int
    module: str


def iter_modules(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level and base:
                base = "." * node.level + base
            elif node.level and not base:
                base = "." * node.level
            if base:
                found.append((node.lineno, base))
            for alias in node.names:
                if base and not base.endswith("."):
                    found.append((node.lineno, f"{base}.{alias.name}"))
                else:
                    found.append((node.lineno, alias.name))
    return found


def scan_source(source: str, *, filename: str = "<memory>") -> list[ImportHit]:
    tree = ast.parse(source)
    return [ImportHit(filename, line, module) for line, module in iter_modules(tree)]


def scan_tree(root: Path) -> list[ImportHit]:
    hits: list[ImportHit] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(ROOT).as_posix()
        hits.extend(scan_source(path.read_text(encoding="utf-8"), filename=rel))
    return hits


def _norm(module: str) -> str:
    return module.lstrip(".")


def matches(module: str, suffix: str) -> bool:
    name = _norm(module)
    return name == suffix or name.startswith(suffix + ".")


def is_channel_or_onebot(module: str) -> bool:
    name = _norm(module)
    if matches(module, "agent.channel") or matches(module, "channel"):
        return True
    return "onebot" in name.split(".")


def is_statebench(module: str) -> bool:
    return matches(module, "evals.statebench") or matches(module, "statebench")


def is_algorithms(module: str) -> bool:
    return matches(module, "agent.algorithms") or matches(module, "algorithms")


def is_harness(module: str) -> bool:
    return matches(module, "agent.harness") or matches(module, "harness")


def is_sqlite(module: str) -> bool:
    return matches(module, "sqlite3")


def domain_send_target(module: str) -> str | None:
    """领域包不得用来发 QQ 消息的 import。返回类别，否则 None。"""
    rules = (
        ("send", ("agent.channel.send", "channel.send")),
        ("onebot", ("agent.channel.onebot", "channel.onebot", "onebot")),
        ("client_ref", ("agent.channel.client_ref", "channel.client_ref")),
    )
    for kind, suffixes in rules:
        if any(matches(module, suffix) for suffix in suffixes):
            return kind
    if "onebot" in _norm(module).split("."):
        return "onebot"
    return None
