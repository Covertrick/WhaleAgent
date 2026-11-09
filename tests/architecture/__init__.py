"""架构边界测试包。`python -m unittest tests.architecture` 会加载这里的用例。"""

from __future__ import annotations


def load_tests(loader, tests, pattern):  # noqa: ARG001
    from tests.architecture import test_boundaries

    tests.addTests(loader.loadTestsFromModule(test_boundaries))
    return tests
