"""依赖边界。不需要 API_KEY、网络或 NapCat。"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from tests.architecture.scan import (
    ROOT,
    domain_send_target,
    is_algorithms,
    is_channel_or_onebot,
    is_harness,
    is_sqlite,
    is_statebench,
    scan_source,
    scan_tree,
)


# agent/life/monitor.py 的定时速递在 register_digest_job 里调用
# agent.channel.send.safe_send_msg。这是既有投递，不是领域包普遍获得发消息权。
# 见 agent/life/monitor.py。onebot / client_ref 即使在这个文件里也不允许。
ALLOWED_DOMAIN_SEND = {
    ("agent/life/monitor.py", "send"),
}

DOMAIN_ROOTS = (
    "agent/knowledge",
    "agent/files",
    "agent/vault",
    "agent/schedules",
    "agent/life",
)


def _qq_schema_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "_fn" and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                names.add(arg.value)
    return names


def _qq_handler_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        target = None
        value = None
        if isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        if not isinstance(target, ast.Name) or target.id != "handlers":
            continue
        if isinstance(value, ast.Dict):
            for key in value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    names.add(key.value)
    return names


class BoundaryTests(unittest.TestCase):
    def test_string_literal_is_not_an_import(self) -> None:
        hits = scan_source('FORBIDDEN = ["onebot", "agent.channel"]\n')
        self.assertEqual(hits, [])

    def test_algorithms_do_not_import_channel_onebot_statebench_or_harness(self) -> None:
        bad = []
        for hit in scan_tree(ROOT / "agent" / "algorithms"):
            if (
                is_channel_or_onebot(hit.module)
                or is_statebench(hit.module)
                or is_harness(hit.module)
                or is_sqlite(hit.module)
            ):
                bad.append(hit)
        self.assertEqual(bad, [])

    def test_harness_does_not_import_channel_or_onebot(self) -> None:
        # harness/evolve/whitelist.py 把 "onebot" 当作禁止出现在自修改文本里的词，不是 import。
        bad = [hit for hit in scan_tree(ROOT / "agent" / "harness") if is_channel_or_onebot(hit.module)]
        self.assertEqual(bad, [])

    def test_domains_do_not_send_except_digest_job(self) -> None:
        bad = []
        for rel in DOMAIN_ROOTS:
            for hit in scan_tree(ROOT / rel):
                kind = domain_send_target(hit.module)
                if kind is None:
                    continue
                if (hit.file, kind) in ALLOWED_DOMAIN_SEND:
                    continue
                bad.append((hit.file, hit.line, hit.module, kind))
        self.assertEqual(bad, [])

    def test_channel_does_not_import_algorithms(self) -> None:
        bad = [hit for hit in scan_tree(ROOT / "agent" / "channel") if is_algorithms(hit.module)]
        self.assertEqual(bad, [])

    def test_application_does_not_import_channel_or_statebench(self) -> None:
        bad = []
        for hit in scan_tree(ROOT / "agent" / "application"):
            if is_channel_or_onebot(hit.module) or is_statebench(hit.module):
                bad.append(hit)
        self.assertEqual(bad, [])

    def test_qq_tool_names_match_skill_manifest(self) -> None:
        from agent.harness.qq_skills import QQ_SKILL_MANIFESTS
        from agent.tools.qq import FORBIDDEN_ON_QQ, QQ_TOOL_NAMES

        qq = ROOT / "agent" / "tools" / "qq.py"
        schemas = _qq_schema_names(qq)
        handlers = _qq_handler_names(qq)
        self.assertEqual(set(QQ_SKILL_MANIFESTS), set(QQ_TOOL_NAMES))
        self.assertEqual(schemas, set(QQ_TOOL_NAMES))
        self.assertEqual(handlers, set(QQ_TOOL_NAMES))
        self.assertTrue(QQ_TOOL_NAMES.isdisjoint(FORBIDDEN_ON_QQ))


if __name__ == "__main__":
    unittest.main()
