"""异步入口冒烟。不连接 NapCat，也不导入评测包。"""

from __future__ import annotations

import ast
import asyncio
import time
import unittest
from pathlib import Path

from agent.channel.async_ingress import OVERFLOW_MESSAGE, AsyncIngress


class AsyncIngressTests(unittest.TestCase):
    def test_same_session_stays_ordered(self) -> None:
        order: list[tuple[str, str]] = []

        def handler(event: dict) -> None:
            order.append(("start", event["mark"]))
            time.sleep(0.05)
            order.append(("end", event["mark"]))

        ingress = AsyncIngress(handler, capacity=4, concurrency=2)
        self.assertTrue(ingress.submit({"session": "s", "mark": "1"}))
        self.assertTrue(ingress.submit({"session": "s", "mark": "2"}))
        asyncio.run(ingress.drain())
        self.assertLess(order.index(("end", "1")), order.index(("start", "2")))

    def test_different_sessions_can_overlap(self) -> None:
        def handler(event: dict) -> None:
            time.sleep(0.1)

        ingress = AsyncIngress(handler, capacity=4, concurrency=2)
        self.assertTrue(ingress.submit({"session": "a", "mark": "a"}))
        self.assertTrue(ingress.submit({"session": "b", "mark": "b"}))
        asyncio.run(ingress.drain())
        self.assertGreaterEqual(ingress.max_inflight, 2)

    def test_overflow_does_not_start(self) -> None:
        called: list[str] = []

        def handler(event: dict) -> None:
            called.append(event["mark"])

        ingress = AsyncIngress(handler, capacity=1, concurrency=1)
        self.assertTrue(ingress.submit({"session": "s", "mark": "1"}))
        self.assertFalse(ingress.submit({"session": "s", "mark": "2"}))
        self.assertEqual(called, [])
        self.assertIn("稍后再叫我", OVERFLOW_MESSAGE)

    def test_cancelled_effect_is_not_replayed(self) -> None:
        called: list[str] = []

        def handler(event: dict) -> None:
            called.append(event["mark"])
            if event["mark"] == "1":
                raise RuntimeError("cancelled")

        ingress = AsyncIngress(handler, capacity=4, concurrency=1)
        self.assertTrue(ingress.submit({"session": "s", "mark": "1", "effect_id": "write-1", "irreversible": True}))
        self.assertTrue(ingress.submit({"session": "s", "mark": "2", "effect_id": "write-1", "irreversible": True}))
        asyncio.run(ingress.drain())
        self.assertEqual(called, ["1"])

    def test_ingress_does_not_import_statebench(self) -> None:
        path = Path(__file__).resolve().parents[2] / "agent" / "channel" / "async_ingress.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
        self.assertFalse(any("statebench" in name for name in modules))


if __name__ == "__main__":
    unittest.main()
