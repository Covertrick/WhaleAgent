"""扫描算法包里的静态 import / from import。

AST 不是沙箱。importlib 和 __import__ 不在这项承诺内。
"""

from __future__ import annotations

import ast
from pathlib import Path


def _is_channel(module: str | None, names: list[str] | None = None) -> bool:
    if module and (module == "agent.channel" or module.startswith("agent.channel.")):
        return True
    if module == "agent" and names:
        return any(name == "channel" or name.startswith("channel.") for name in names)
    if module is None and names:
        return any(name == "agent.channel" or name.startswith("agent.channel.") for name in names)
    return False


def scan_tree(tree: ast.AST, *, filename: str = "<memory>") -> list[dict[str, object]]:
    hits: list[dict[str, object]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_channel(alias.name):
                    hits.append(
                        {
                            "file": filename,
                            "line": node.lineno,
                            "statement": f"import {alias.name}",
                        }
                    )
        elif isinstance(node, ast.ImportFrom):
            imported = [alias.name for alias in node.names]
            if _is_channel(node.module, imported):
                hits.append(
                    {
                        "file": filename,
                        "line": node.lineno,
                        "statement": f"from {node.module} import {', '.join(imported)}",
                    }
                )
    return hits


def scan_source(source: str, *, filename: str = "<memory>") -> list[dict[str, object]]:
    return scan_tree(ast.parse(source), filename=filename)


def scan_static_channel_imports(root: str | Path) -> list[dict[str, object]]:
    base = Path(root)
    hits: list[dict[str, object]] = []
    for path in sorted(base.glob("**/*.py")):
        hits.extend(scan_source(path.read_text(encoding="utf-8"), filename=str(path)))
    return hits
