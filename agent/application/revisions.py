"""受控修订。内容哈希不能排序，但同一来源的读取顺序可以登记。"""

from __future__ import annotations


class ContentRevisionLedger:
    """同一来源、同一哈希保持同一个修订号。内容变了才登记下一个修订。"""

    def __init__(self) -> None:
        self._history: dict[tuple[str, str], list[tuple[str, str]]] = {}
        self._values: dict[str, dict[str, str]] = {}

    def assign(self, fact_key: str, source_uri: str, digest: str, value: str) -> tuple[str, str]:
        """返回修订号和状态。没有来源或哈希时不编造版本。"""
        uri = (source_uri or "").strip()
        token = (digest or "").strip().lower()
        if not uri or len(token) != 64 or any(char not in "0123456789abcdef" for char in token):
            return "", "UNKNOWN"
        key = (fact_key, uri)
        history = self._history.setdefault(key, [])
        version = next((name for seen, name in history if seen == token), "")
        if not version:
            version = f"v{len(history) + 1}"
            history.append((token, version))
        known = self._values.setdefault(fact_key, {})
        known[uri] = value
        distinct = {item for item in known.values() if item}
        if len(distinct) > 1:
            return version, "UNKNOWN"
        return version, "VALID"

    def conflicted(self, fact_key: str) -> bool:
        values = {item for item in self._values.get(fact_key, {}).values() if item}
        return len(values) > 1
