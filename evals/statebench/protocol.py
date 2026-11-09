"""事先写明的风险候选和预算。一次运行只加载其中一个风险模式。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from agent.algorithms.types import RiskRule
from evals.statebench.contracts import checkpoint_contract_sha256, scoring_contract_sha256
from evals.statebench.hashing import sha256_text

ROOT = Path(__file__).resolve().parent
EXPERIMENT_PATH = ROOT / "experiment.yaml"
FROZEN_PATH = ROOT / "frozen_config.json"
ALLOWED_MODES = ("before_irreversible", "evidence_age")


def load_experiment() -> dict[str, Any]:
    return yaml.safe_load(EXPERIMENT_PATH.read_text(encoding="utf-8"))


def _candidate_map(experiment: dict[str, Any]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for item in experiment.get("risk", {}).get("candidates") or []:
        mode = str(item.get("mode") or "")
        if mode in found:
            raise RuntimeError(f"风险候选重复: {mode}")
        found[mode] = item
    if tuple(found) != ALLOWED_MODES:
        raise RuntimeError("风险候选必须正好是 before_irreversible 和 evidence_age")
    age = found["evidence_age"].get("max_age")
    if age != 10:
        raise RuntimeError("evidence_age 的 max_age 必须事先固定为 10")
    return found


def risk_rule(experiment: dict[str, Any], mode: str | None = None) -> RiskRule:
    candidates = _candidate_map(experiment)
    selected = mode or str(experiment.get("risk", {}).get("active") or "")
    if selected not in candidates:
        raise RuntimeError(f"未知风险模式: {selected}")
    if selected == "evidence_age":
        return RiskRule("evidence_age", 10)
    return RiskRule("before_irreversible")


def budget_of(experiment: dict[str, Any], *, observe: int | None = None) -> dict[str, int]:
    raw = experiment.get("budget") or {}
    return {
        "observe": int(observe if observe is not None else raw.get("observe") or 3),
        "replan": int(raw.get("replan") or 2),
        "tools": int(raw.get("max_tool_calls") or 8),
        "rounds": int(experiment.get("max_rounds") or 6),
        "observe_fallback": int(raw.get("observe_fallback") or 4),
    }


def load_frozen() -> dict[str, Any]:
    if not FROZEN_PATH.exists():
        raise RuntimeError("缺少冻结配置，先运行 python -m evals.statebench.freeze_config --mock")
    return json.loads(FROZEN_PATH.read_text(encoding="utf-8"))


def frozen_risk(config: dict[str, Any]) -> RiskRule:
    mode = str(config.get("risk_mode") or "")
    if mode == "evidence_age":
        if int(config.get("max_age") or 0) != 10:
            raise RuntimeError("冻结配置里的证据年龄不是事先写明的 10")
        return RiskRule("evidence_age", 10)
    if mode == "before_irreversible":
        return RiskRule("before_irreversible")
    raise RuntimeError(f"冻结配置的风险模式无法使用: {mode}")


def contract_hashes() -> dict[str, str]:
    from evals.statebench.catalog import MANIFEST_PATH

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    scoring = scoring_contract_sha256()
    checkpoint = checkpoint_contract_sha256()
    if manifest.get("scoring_contract_sha256") != scoring or manifest.get("checkpoint_contract_sha256") != checkpoint:
        raise RuntimeError("评分或检查点契约与冻结清单不一致")
    return {
        "tasks_sha256": manifest["tasks_sha256"],
        "splits_sha256": manifest["splits_sha256"],
        "scoring_contract_sha256": scoring,
        "checkpoint_contract_sha256": checkpoint,
    }


def sha256_plan(text: str) -> str:
    return sha256_text(text)
