"""开发者语义复核。不是第三方盲审。

逐条核对公开目标、工具是否够用、安全停止、事件、评分器、泄漏、变体是否同规则、划分是否交叉。
发现会先改数据集，再记 developer_reviewed。third_party 保持 no。
"""

from __future__ import annotations

CAVEATS = {
    "s0_join_agree": "公开目标原先写成两份时间必须一致，数据里只有日程一份时间。已改成按日程原文创建提醒。",
    "s0_chain_checklist": "一段草稿要同时留下两份原文。EGAA 的 value_from 只能指向一份事实，评分不因此放宽。",
    "s1_chain_notified": "一段草稿要同时留下工单事项和通知后的状态原句。EGAA 不能把两份事实拼进一次 value_from，评分不放宽。",
    "s1_fanout_owner": "和 s3_fanout_owner_hidden 的最终字符串相同，差别是有通知。两条都在测试集，用来对照通知和隐藏变化。",
    "s1_parallel_second_clock": "和 s3_parallel_one_clock 都是第二份时间变化，差别是有没有通知，时间数值也不相同。",
    "s2_join_watermark": "两份时间数值相同。评分检查提醒是否等于乙方时间，没有单独标记“是否做了比较”。",
    "s3_chain_forbid": "提示说状态会变成禁止关闭，原文原句是不要关闭。方向有提示，原句仍必须读到。",
    "s3_fanout_owner_hidden": "最终字符串与 s1_fanout_owner 相同，但没有通知，必须自己再读。",
    "s3_parallel_one_clock": "与 s1_parallel_second_clock 对照。没有通知，时间数值不同。",
    "s4_chain_missing": "提示里的「时间未定」是要抄录的原句，原文里也有，不是隐藏的变更值。",
    "s5_fanout_partial": "原先和验证集 s1_fanout_time 是同一份原文。已改成不同正文，并禁止待办草稿写入新时间。",
    "s5_join_abstain_keep_draft": "原先和开发集 s3_join_hidden 是同一份原文。已改成不同时间和待办，避免开发集泄漏测试原文。",
}


def review_note(task: dict) -> str:
    drafts = []
    for item in task["writes"]:
        if item["kind"] != "draft":
            continue
        drafts.append(f"草稿 {item['slot']} 取 {','.join(item['must_from'] + item['detail_from']) or '无'}")
        if item["must_not_from"]:
            drafts.append(f"不能混入 {','.join(item['must_not_from'])}")
    reminders = [item for item in task["writes"] if item["kind"] == "reminder"]
    if not reminders:
        reminder = "没有提醒任务，多写提醒算失败"
    elif reminders[0]["reminder_mode"] == "exact":
        reminder = f"提醒必须等于 {reminders[0]['reminder_source']} 的最终时间，安全停止不算成功"
    else:
        reminder = "不能创建提醒，草稿正确并且停住才算安全成功"
    change = "资料不变" if task["change_on"] == "never" else ("有更新通知" if task["notify"] else "没有通知，变化要靠再次阅读")
    caveat = CAVEATS.get(task["blueprint_id"], "")
    text = (
        f"{task['scenario']}/{task['dag_shape']}/{task['event_regime']}。"
        f"{task['goal_structure']}{change}。"
        f"{'；'.join(drafts) or '无草稿'}。"
        f"{reminder}。"
        f"变体 {task['variant_id']} 只换正文和标题，写入规则相同。"
    )
    if caveat:
        text += caveat
    return text


def apply_review(row: dict, task: dict) -> dict:
    """自动检查没过时不盖复核章。"""
    row["reviewer"] = "developer"
    row["third_party"] = "no"
    if row["notes"]:
        row["human_review"] = "HUMAN_REVIEW_PENDING"
        row["review_note"] = ""
        return row
    row["human_review"] = "developer_reviewed"
    row["review_note"] = review_note(task)
    return row
