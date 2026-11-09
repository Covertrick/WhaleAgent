"""从执行器文本判断效果是否已经确认。"""

from __future__ import annotations


def effect_status(content: str) -> str:
    text = content or ""
    if (
        text.startswith("UNKNOWN:")
        or "不会自动再做" in text
        or "不确定有没有做成" in text
    ):
        return "UNVERIFIED"
    if text.startswith(("Error:", "沙箱拒绝", "precondition", "postcondition")):
        return "FAILED"
    return "CONFIRMED"
