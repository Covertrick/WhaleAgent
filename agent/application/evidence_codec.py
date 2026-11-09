"""把工具结果收成证据。显式 vN 优先；否则只接受受控修订账登记过的内容哈希。"""

from __future__ import annotations

import re

from agent.algorithms.types import Evidence
from agent.application.revisions import ContentRevisionLedger

_VERSION = re.compile(r"^v\d+$")
_FIELD = re.compile(r"^([A-Za-z0-9_]+)\s*[:：]\s*(.*)$")


def monotonic_version(token: str | None) -> str | None:
    """只接受 v 加十进制整数。内容哈希、记录 id、自然语言都不是可排序版本。"""
    text = (token or "").strip()
    if _VERSION.fullmatch(text):
        return text
    return None


def parse_evidence_block(content: str) -> dict[str, str]:
    """读取工具自愿返回的 EVIDENCE 块。没有这块时返回空字典。"""
    lines = (content or "").splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == "EVIDENCE"), None)
    if start is None:
        return {}
    fields: dict[str, str] = {}
    for line in lines[start + 1 :]:
        matched = _FIELD.match(line.strip())
        if matched is None:
            if fields:
                break
            continue
        fields[matched.group(1)] = matched.group(2).strip()
    return fields


def evidence_from_tool(
    *,
    fact_key: str,
    content: str,
    observed_at: int,
    fallback_version: str | None = None,
    fallback_value: str | None = None,
    fallback_uri: str = "",
    ledger: ContentRevisionLedger | None = None,
) -> Evidence:
    """工具文本优先。调用方只能补用户消息里已经写明的版本和值。"""
    fields = parse_evidence_block(content)
    version = monotonic_version(fields.get("source_version")) or monotonic_version(fallback_version)
    if fields.get("value"):
        value = fields["value"]
    elif fallback_value:
        value = fallback_value
    else:
        value = (content or "").strip()
    uri = fields.get("source_uri") or fallback_uri or ""
    status = "VALID" if version else "UNKNOWN"
    if not version and ledger is not None:
        minted, status = ledger.assign(fact_key, uri, fields.get("content_sha256") or "", value)
        version = minted
    return Evidence(
        id=f"ev:{fact_key}",
        fact_key=fact_key,
        value=value,
        source_id=uri or "tool",
        source_version=version or "unversioned",
        observed_at=observed_at,
        status=status if version else "UNKNOWN",
    )
