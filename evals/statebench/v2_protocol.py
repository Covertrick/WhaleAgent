"""StateBench v2 协议。

这里不读取、不改写 v1 的 40 道冻结题，也不发起模型请求。
这三张任务和五种方法还没有作为人工核对后的测试集跑完。
已有的真实模型数字来自 `v2_live.py`，不是本模块的 TASKS。
"""

from __future__ import annotations

VISIBLE_FIELDS = ("task_id", "prompt", "branches", "tool_schemas")
HIDDEN_FIELDS = frozenset(
    {
        "events",
        "initial_facts",
        "success",
        "constraints",
        "expected",
        "environment_event",
        "expected_world",
        "source_key",
        "target_key",
    }
)
METHODS = (
    "live_react",
    "planned_without_evidence_policy",
    "egaa_selective",
    "always_refresh",
    "always_full_replan",
)

# 三张依赖图只描述用户能看见的分支，不包含标准答案。
TASKS = (
    {
        "task_id": "v2_conflict",
        "prompt": "两份项目资料给出了不同的截止时间。先指出冲突，再决定哪一步可以继续，哪一步必须停下来问我。",
        "branches": ("note_draft", "reminder"),
        "tool_schemas": ("search_vault", "write_vault_draft", "schedule_list", "schedule_reminder"),
    },
    {
        "task_id": "v2_partial_change",
        "prompt": "会议时间可能变化。笔记草稿如果仍依据未变化的资料，就不要重写；提醒必须使用最新的截止时间。",
        "branches": ("note_draft", "reminder"),
        "tool_schemas": ("search_vault", "write_vault_draft", "schedule_reminder"),
    },
    {
        "task_id": "v2_unknown_effect",
        "prompt": "创建提醒如果没有确认回执，先查询已有提醒。查不清就停下来问我，不要再创建一次。",
        "branches": ("reminder", "status_check"),
        "tool_schemas": ("schedule_reminder", "schedule_list"),
    },
)


def visible_task(task: dict) -> dict:
    """模型循环和 EGAA 只能拿这份视图。隐藏事件和标准答案留在评分器。"""
    leaked = HIDDEN_FIELDS.intersection(task)
    if leaked:
        raise ValueError("visible_task 拒绝隐藏字段: " + ",".join(sorted(leaked)))
    return {key: task[key] for key in VISIBLE_FIELDS if key in task}
