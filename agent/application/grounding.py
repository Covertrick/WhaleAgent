"""从工具原文抽取可核对的事实。抽取结果必须能在原文里找到。"""

from __future__ import annotations

import hashlib
import json
import re

from agent.algorithms.types import Evidence
from agent.application.evidence_codec import parse_evidence_block
from agent.application.revisions import ContentRevisionLedger

ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00")


def model_grounder():
    """模型不能把原文里没有的片段标成 VALID。修订账由本轮 Policy 传入。"""
    seen_times: dict[str, set[str]] = {}

    def ground(*, fact_key: str, content: str, observed_at: int, ledger: ContentRevisionLedger) -> Evidence:
        seen_times[fact_key] = set(ISO.findall(content or ""))
        times = set().union(*seen_times.values()) if seen_times else set()
        ground.deadline_conflict = len(times) > 1
        value, usable = _extract(fact_key, content or "")
        if fact_key == "project.deadline" and ground.deadline_conflict:
            usable = False
        fields = parse_evidence_block(content or "")
        uri = fields.get("source_uri") or f"observed:{fact_key}"
        digest = _digest(fields.get("content_sha256"), content or "")
        version, status = ledger.assign(fact_key, uri, digest, value if usable else "")
        if not usable:
            status = "UNKNOWN"
        return Evidence(
            id=f"ev:{fact_key}",
            fact_key=fact_key,
            value=value if usable else (content or "").strip(),
            source_id=uri,
            source_version=version or "unversioned",
            observed_at=observed_at,
            status=status if version else "UNKNOWN",
        )

    return ground


def _digest(declared: str | None, content: str) -> str:
    token = (declared or "").strip().lower()
    if len(token) == 64 and all(char in "0123456789abcdef" for char in token):
        return token
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _extract(fact_key: str, content: str) -> tuple[str, bool]:
    if not content.strip() or content.startswith("Error:"):
        return "", False
    if fact_key == "project.deadline" and not ISO.findall(content):
        return "", False
    payload = _ask(fact_key, content)
    span = str(payload.get("evidence_span") or "")
    if not span or span not in content:
        return "", False
    if fact_key == "project.deadline":
        value = str(payload.get("value") or "")
        if not ISO.fullmatch(value) or value not in content:
            return "", False
        return value, True
    lines = ["待办草稿"]
    for item in payload.get("todos") or []:
        if not isinstance(item, dict):
            return "", False
        text = str(item.get("text") or "")
        owner = str(item.get("owner") or "未写明")
        if not text or text not in content:
            return "", False
        if owner != "未写明" and owner not in content:
            return "", False
        lines.append(f"- {text}（负责人：{owner}）")
    if len(lines) == 1:
        return "", False
    lines.append(f"来源：「{span}」")
    return "\n".join(lines), True


def _ask(fact_key: str, content: str) -> dict:
    from agent.core.llm import usage_phase
    from agent.core.model_step import model_step

    phase = usage_phase.set("extract")
    try:
        raw = model_step(
            [
                {"role": "system", "content": "只输出 JSON。text、owner、value、evidence_span 都必须是资料中的连续原文。"},
                {
                    "role": "user",
                    "content": (
                        f"fact_key={fact_key}\n"
                        "抽取待办、负责人和截止时间。没有负责人就让 owner 为「未写明」。"
                        "没有 ISO8601 截止时间就让 value 为空字符串。\n"
                        '输出 {"todos":[{"text":"","owner":""}],"value":"","evidence_span":""}\n'
                        f"资料：\n{content}"
                    ),
                },
            ],
            tools=None,
            max_tokens=1500,
            temperature=0,
        )
    finally:
        usage_phase.reset(phase)
    text = str(raw.get("content") or "")
    if "{" not in text:
        text = str(raw.get("reasoning_content") or text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
