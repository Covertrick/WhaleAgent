"""Harness 执行口测试。`python -m unittest tests.harness` 会加载这里的用例。"""

from __future__ import annotations


def load_tests(loader, tests, pattern):  # noqa: ARG001
    from tests.harness import test_executor_port

    tests.addTests(loader.loadTestsFromModule(test_executor_port))
    return tests
