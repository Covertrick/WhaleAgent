"""48 个蓝图。同一蓝图的两个变体共享依赖和事件规则，正文不同。"""

from __future__ import annotations

from evals.statebench.v3.world import Source, Surface, TaskSpec, Write, graph_shape

_ASK = {
    "S0": "阅读之后资料不会再改。",
    "S1": "若出现更新通知，以重新读到的原文为准。",
    "S2": "与目标无关的更新不要写进结果。",
    "S3": "没有更新通知。不要提交已经变掉的旧值。",
    "S4": "证据冲突或缺失时不要编造。",
    "S5": "只有一部分资料会变。没变的内容保持原样。",
}

DEV_IDS = (
    "s0_parallel_stable",
    "s0_fanout_stable",
    "s1_join_notified",
    "s1_chain_notified",
    "s2_parallel_irrelevant",
    "s2_fanout_irrelevant",
    "s3_chain_hidden",
    "s3_join_hidden",
    "s4_join_conflict",
    "s4_chain_missing",
    "s5_parallel_partial",
    "s5_fanout_partial",
)


def _prompt(titles: dict[str, str], goal: str, scenario: str) -> str:
    names = "、".join(f"「{title}」" for title in titles.values())
    return f"请阅读{names}。{goal}{_ASK[scenario]}只能使用工具读到的原文，不要编造时间、负责人或提醒。"


def _doc(sid: str, title: str, sentence: str, sentence2: str | None, phrase: str, token: str = "", token2: str = "", detail: str = "") -> Source:
    v1 = f"{title}｜{sentence}"
    v2 = v1 if sentence2 is None else f"{title}｜{sentence2}"
    return Source(sid, v1, v2, phrase, token, token2 or token, detail)


def _todo_as(sid: str, title: str, todo: str) -> Source:
    return _doc(sid, title, f"待办：{todo}。", None, todo)


def _todo(title: str, todo: str, detail: str = "") -> Source:
    tail = f"负责人：{detail}。" if detail else ""
    return _doc("notes", title, f"待办：{todo}。{tail}", None, todo, detail=detail)


def _when(sid: str, title: str, old: str, new: str | None) -> Source:
    final = old if new is None else new
    second = None if new is None else f"时间：{final}。"
    return _doc(sid, title, f"时间：{old}。", second, "", old, final)


def _say(sid: str, title: str, old: str, new: str | None, label: str) -> Source:
    final = old if new is None else new
    second = None if new is None else f"{label}：{final}。"
    return _doc(sid, title, f"{label}：{old}。", second, final)


def _owned(title: str, todo: str, old_owner: str, new_owner: str | None) -> Source:
    final = old_owner if new_owner is None else new_owner
    second = None if new_owner is None else f"待办：{todo}。负责人：{final}。"
    return _doc("notes", title, f"待办：{todo}。负责人：{old_owner}。", second, todo, detail=final)


def _both(title: str, todo: str, old: str, new: str | None) -> Source:
    final = old if new is None else new
    second = None if new is None else f"待办：{todo}。时间：{final}。"
    return _doc("notes", title, f"待办：{todo}。时间：{old}。", second, todo, old, final)


def _draft(wid: str, needs: tuple[str, ...], must_from: tuple[str, ...] = (), detail_from: tuple[str, ...] = (), must_not_from: tuple[str, ...] = ()) -> Write:
    return Write(wid, "draft", needs, slot=wid, must_from=must_from, detail_from=detail_from, must_not_from=must_not_from)


def _remind(needs: tuple[str, ...], mode: str, source: str) -> Write:
    return Write("reminder", "reminder", needs, reminder_mode=mode, reminder_source=source)


def _one(blueprint_id, split, scenario, shape, domain, risk, regime, goal, notify, writes, left, right, genres) -> TaskSpec:
    changed = any(doc.changes for docs in (left, right) for doc in docs)
    spec = TaskSpec(
        blueprint_id, split, scenario, shape, domain, goal, risk, regime,
        "after_first_read" if changed else "never", notify, writes, goal,
        (
            Surface(genres[0], {doc.sid: doc.v1.split("｜", 1)[0] for doc in left}, left, _prompt({doc.sid: doc.v1.split("｜", 1)[0] for doc in left}, goal, scenario)),
            Surface(genres[1], {doc.sid: doc.v1.split("｜", 1)[0] for doc in right}, right, _prompt({doc.sid: doc.v1.split("｜", 1)[0] for doc in right}, goal, scenario)),
        ),
    )
    actual = graph_shape(writes)
    if actual != shape:
        raise RuntimeError(f"{blueprint_id} 标成 {shape}，依赖图实际是 {actual}")
    return spec


def build_catalog() -> tuple[TaskSpec, ...]:
    add = _one
    rows = [
        add("s0_parallel_stable", "dev", "S0", "parallel", "vault+schedule", "reversible+irreversible", "stable",
            "待办草稿只依赖纪要，提醒只依赖另一份时间，两条分支互不引用。", False,
            (_draft("todo", ("r_notes",), ("notes",)), _remind(("r_clock",), "exact", "clock")),
            (_todo("会议纪要", "整理实验记录"), _when("clock", "截止说明", "2026-12-01T09:00:00+08:00", None)),
            (_todo("工单", "补齐备份校验"), _when("clock", "排期", "2026-12-03T18:00:00+08:00", None)),
            ("会议", "工单")),
        add("s0_fanout_stable", "dev", "S0", "fanout", "vault", "reversible", "stable",
            "同一份纪要同时写出待办草稿和负责人备忘，没有第二来源。", False,
            (_draft("todo", ("r_notes",), ("notes",)), _draft("owner", ("r_notes",), detail_from=("notes",))),
            (_todo("项目纪要", "更新部署说明", "林夏"),),
            (_todo("发布邮件", "更新回滚步骤", "周宁"),),
            ("纪要", "邮件")),
        add("s0_chain_checklist", "val", "S0", "chain", "vault", "reversible", "stable",
            "先读清单再读结论，草稿必须同时留下清单事项和结论原句。", False,
            (_draft("result", ("r2",), ("notes", "clock")),),
            (_todo("检查清单", "逐项核对"), _say("clock", "结论页", "可以归档", None, "结论")),
            (_todo("值守单", "确认告警"), _say("clock", "结论文档", "观察结束", None, "结论")),
            ("清单", "值守")),
        add("s0_join_agree", "val", "S0", "join", "vault+schedule", "irreversible", "stable",
            "两份时间一致才创建提醒，草稿仍只写纪要里的待办。", False,
            (_draft("todo", ("r_notes",), ("notes",)), _remind(("r_notes", "r_clock"), "exact", "clock")),
            (_todo("例会记录", "提交周报"), _when("clock", "共享日程", "2026-12-05T09:30:00+08:00", None)),
            (_todo("周报提纲", "核对引用"), _when("clock", "共享日历", "2026-12-05T14:00:00+08:00", None)),
            ("例会", "周报")),
        add("s0_parallel_two_drafts", "test", "S0", "parallel", "vault", "reversible", "stable",
            "两份独立说明各写一段草稿，不创建提醒。", False,
            (_draft("left", ("r_notes",), ("notes",)), _draft("right", ("r_extra",), ("extra",))),
            (_todo("接口说明", "补齐接口示例"), _say("extra", "错误码表", "保留旧错误码", None, "条目")),
            (_todo("迁移说明", "双写一周"), _say("extra", "回滚说明", "先停新写入", None, "条目")),
            ("接口", "迁移")),
        add("s0_fanout_memo_index", "test", "S0", "fanout", "vault", "reversible", "stable",
            "一份备忘同时产出正文草稿和索引行。", False,
            (_draft("body", ("r_notes",), ("notes",)), _draft("index", ("r_notes",), detail_from=("notes",))),
            (_todo("实验备忘", "校准传感器", "台架 A"),),
            (_todo("采样备忘", "复核标定", "台架 B"),),
            ("实验", "采样")),
        add("s0_chain_three_reads", "test", "S0", "chain", "vault", "reversible", "stable",
            "草稿只能在读完第三份签核后写下签核原句。", False,
            (_draft("signoff", ("r3",), ("tail",)),),
            (_todo("申请单", "开通只读权限"), _say("extra", "安全复查", "没有外联", None, "复查"), _say("tail", "签核", "同意开通", None, "签核")),
            (_todo("账号单", "加入审计组"), _say("extra", "权限复查", "没有写权限", None, "复查"), _say("tail", "审批", "同意加入", None, "签核")),
            ("申请", "账号")),
        add("s0_join_archive", "test", "S0", "join", "schedule", "irreversible", "stable",
            "两份状态都读到之后，才按时间那一份创建归档提醒。", False,
            (_remind(("r_notes", "r_clock"), "exact", "clock"),),
            (_say("notes", "归档条件", "日志已封存", None, "条件"), _when("clock", "归档时间", "2026-12-07T18:00:00+08:00", None)),
            (_say("notes", "封存条件", "索引已完成", None, "条件"), _when("clock", "封存时间", "2026-12-08T18:00:00+08:00", None)),
            ("归档", "封存")),
        add("s1_join_notified", "dev", "S1", "join", "vault+schedule", "irreversible", "notified",
            "纪要里的待办不改。提醒必须同时依据纪要和通知后的新时间。", True,
            (_draft("todo", ("r_notes",), ("notes",)), _remind(("r_notes", "r_clock"), "exact", "clock")),
            (_todo("会议纪要", "整理实验记录"), _when("clock", "截止说明", "2026-12-01T09:00:00+08:00", "2026-12-04T15:00:00+08:00")),
            (_todo("看板卡片", "补测试数据"), _when("clock", "日期字段", "2026-12-02T10:00:00+08:00", "2026-12-06T11:30:00+08:00")),
            ("纪要", "看板")),
        add("s1_chain_notified", "dev", "S1", "chain", "vault", "reversible", "notified",
            "先读工单再读状态。草稿必须同时留下工单事项和通知后的状态原句。", True,
            (_draft("status", ("r2",), ("notes", "clock")),),
            (_todo("工单正文", "关闭前复核"), _say("clock", "状态页", "处理中", "可以关闭", "状态")),
            (_todo("值守记录", "结束前复核"), _say("clock", "最新通知", "仍在观察", "观察结束", "状态")),
            ("工单", "值守")),
        add("s1_parallel_clock", "val", "S1", "parallel", "vault+schedule", "reversible+irreversible", "notified",
            "草稿分支保持不变，只有提醒分支跟随通知后的时间。", True,
            (_draft("todo", ("r_notes",), ("notes",)), _remind(("r_clock",), "exact", "clock")),
            (_todo("发布说明", "更新回滚步骤"), _when("clock", "上线窗口", "2026-12-03T21:00:00+08:00", "2026-12-05T21:00:00+08:00")),
            (_todo("变更说明", "补监控截图"), _when("clock", "变更窗口", "2026-12-09T20:00:00+08:00", "2026-12-11T20:00:00+08:00")),
            ("发布", "变更")),
        add("s1_fanout_time", "val", "S1", "fanout", "vault+schedule", "reversible+irreversible", "notified",
            "待办句子和截止时间来自同一份原文。通知只改时间，两路输出都从这份原文重新取。", True,
            (_draft("todo", ("r_notes",), ("notes",)), _remind(("r_notes",), "exact", "notes")),
            (_both("项目纪要", "整理实验记录", "2026-12-01T09:00:00+08:00", "2026-12-06T13:00:00+08:00"),),
            (_both("计划书", "补齐监控", "2026-12-08T16:00:00+08:00", "2026-12-10T16:00:00+08:00"),),
            ("纪要", "计划")),
        add("s1_parallel_second_clock", "test", "S1", "parallel", "schedule", "irreversible", "notified",
            "两份时间彼此独立。只有第二份会收到通知，提醒跟第二份的新时间。", True,
            (_draft("first", ("r_notes",), ("notes",)), _remind(("r_extra",), "exact", "extra")),
            (_say("notes", "内部截止", "保持原计划", None, "安排"), _when("extra", "外部截止", "2026-12-02T09:00:00+08:00", "2026-12-12T09:00:00+08:00")),
            (_say("notes", "联调安排", "保持原顺序", None, "安排"), _when("extra", "验收时间", "2026-12-04T09:00:00+08:00", "2026-12-14T09:00:00+08:00")),
            ("内部", "联调")),
        add("s1_chain_middle", "test", "S1", "chain", "vault", "reversible", "notified",
            "长链的中间一份资料会更新。草稿只采用中间这份通知后的原句。", True,
            (_draft("middle", ("r2",), ("extra",)),),
            (_todo("封面", "不要改封面"), _say("extra", "范围说明", "只改接口", "补上错误码", "范围"), _say("tail", "附录", "没有新增依赖", None, "附录")),
            (_todo("封面页", "不要改封面"), _say("extra", "范围段落", "只改文案", "补上空状态", "范围"), _say("tail", "附录页", "没有改导航", None, "附录")),
            ("封面", "封面页")),
        add("s1_join_reread", "test", "S1", "join", "vault+schedule", "irreversible", "notified",
            "负责人和时间都要读到。通知只改时间，提醒用新时间，负责人仍用原文。", True,
            (_draft("owner", ("r_notes",), detail_from=("notes",)), _remind(("r_notes", "r_clock"), "exact", "clock")),
            (_todo("任务单", "准备验收材料", "赵衡"), _when("clock", "验收时间", "2026-12-02T10:00:00+08:00", "2026-12-09T10:00:00+08:00")),
            (_todo("排期单", "预约场地", "陈舟"), _when("clock", "场地时间", "2026-12-06T15:00:00+08:00", "2026-12-13T15:00:00+08:00")),
            ("任务", "排期")),
        add("s1_fanout_owner", "test", "S1", "fanout", "vault", "reversible", "notified",
            "同一份名单更新了负责人。待办保持，负责人备忘改用通知后的人名。", True,
            (_draft("todo", ("r_notes",), ("notes",)), _draft("owner", ("r_notes",), detail_from=("notes",))),
            (_owned("值班名单", "接听告警", "旧值班", "新值班"),),
            (_owned("支持名单", "回复工单", "旧支持", "新支持"),),
            ("值班", "支持")),
        add("s2_parallel_irrelevant", "dev", "S2", "parallel", "vault+schedule", "reversible+irreversible", "notified_irrelevant",
            "会议待办和提醒照写。附件标签即使有通知，也不进入待办或提醒。", True,
            (_draft("todo", ("r_notes",), ("notes",), must_not_from=("extra",)), _remind(("r_clock",), "exact", "clock")),
            (_todo("会议待办", "整理实验记录"), _when("clock", "截止说明", "2026-12-01T09:00:00+08:00", None), _noise("附件标签", "图片", "截图")),
            (_todo("需求待办", "补齐接口示例"), _when("clock", "需求时间", "2026-12-02T11:00:00+08:00", None), _noise("封面文件", "封面甲", "封面乙")),
            ("会议", "需求")),
        add("s2_fanout_irrelevant", "dev", "S2", "fanout", "vault", "reversible", "notified_irrelevant",
            "两段草稿都只来自纪要。第三份颜色通知不进入任何草稿。", True,
            (_draft("body", ("r_notes",), ("notes",), must_not_from=("extra",)), _draft("owner", ("r_notes",), detail_from=("notes",), must_not_from=("extra",))),
            (_todo("设计纪要", "按钮文案", "林夏"), _noise("颜色通知", "蓝色", "灰色")),
            (_todo("图标备注", "空状态", "周宁"), _noise("版本通知", "版本三", "版本四")),
            ("设计", "图标")),
        add("s2_chain_footnote", "val", "S2", "chain", "vault", "reversible", "notified_irrelevant",
            "结论句来自第二份正文。文末脚注有通知，也不进入结论草稿。", True,
            (_draft("result", ("r2",), ("clock",), must_not_from=("extra",)),),
            (_todo("正文", "核对引用"), _say("clock", "结论", "维持原结论", None, "结论"), _noise("脚注", "脚注甲", "脚注乙")),
            (_todo("正文页", "核对数字"), _say("clock", "结论页", "维持原数字", None, "结论"), _noise("批注", "批注甲", "批注乙")),
            ("正文", "正文页")),
        add("s2_join_third", "val", "S2", "join", "vault+schedule", "irreversible", "notified_irrelevant",
            "提醒只由纪要和日程共同决定。第三份水印通知不改变这个决定。", True,
            (_draft("todo", ("r_notes",), ("notes",), must_not_from=("extra",)), _remind(("r_notes", "r_clock"), "exact", "clock")),
            (_todo("纪要", "整理实验记录"), _when("clock", "日程", "2026-12-01T09:00:00+08:00", None), _noise("水印", "水印甲", "水印乙")),
            (_todo("备忘", "提交周报"), _when("clock", "日历", "2026-12-03T09:00:00+08:00", None), _noise("印章", "印章甲", "印章乙")),
            ("纪要", "备忘")),
        add("s2_parallel_rename", "test", "S2", "parallel", "vault", "reversible", "notified_irrelevant",
            "两段正稿各自依赖自己的原文。旁边的文件改名通知不进入正稿。", True,
            (_draft("left", ("r_notes",), ("notes",), must_not_from=("tail",)), _draft("right", ("r_extra",), ("extra",), must_not_from=("tail",))),
            (_todo("说明甲", "补齐示例"), _say("extra", "说明乙", "保留旧示例", None, "条目"), _noise_as("tail", "文件名", "旧文件名", "新文件名")),
            (_todo("手册甲", "补齐命令"), _say("extra", "手册乙", "保留旧命令", None, "条目"), _noise_as("tail", "附件名", "旧附件名", "新附件名")),
            ("说明", "手册")),
        add("s2_fanout_color", "test", "S2", "fanout", "vault", "reversible", "notified_irrelevant",
            "一份议程写出两段草稿。日历颜色通知不进入这两段。", True,
            (_draft("topic", ("r_notes",), ("notes",), must_not_from=("extra",)), _draft("owner", ("r_notes",), detail_from=("notes",), must_not_from=("extra",))),
            (_todo("议程", "确定发言顺序", "林夏"), _noise("日历颜色", "蓝色", "灰色")),
            (_todo("流程", "确定演示顺序", "周宁"), _noise("标签颜色", "绿色", "黄色")),
            ("议程", "流程")),
        add("s2_chain_footer", "test", "S2", "chain", "vault", "reversible", "notified_irrelevant",
            "第三份才是要抄的签注。页脚通知不进入签注草稿。", True,
            (_draft("signoff", ("r3",), ("tail",), must_not_from=("extra",)),),
            (_todo("首页", "不要改首页"), _noise("页脚", "页脚甲", "页脚乙"), _say("tail", "签注", "同意留档", None, "签注")),
            (_todo("目录", "不要改目录"), _noise("页眉", "页眉甲", "页眉乙"), _say("tail", "批签", "同意存档", None, "签注")),
            ("首页", "目录")),
        add("s2_join_watermark", "test", "S2", "join", "schedule", "irreversible", "notified_irrelevant",
            "两份时间一致才提醒。水印通知不参与这个判断。", True,
            (_remind(("r_notes", "r_clock"), "exact", "clock"),),
            (_when("notes", "甲方时间", "2026-12-07T18:00:00+08:00", None), _when("clock", "乙方时间", "2026-12-07T18:00:00+08:00", None), _noise("水印", "浅色", "深色")),
            (_when("notes", "出发时间", "2026-12-08T08:00:00+08:00", None), _when("clock", "集合时间", "2026-12-08T08:00:00+08:00", None), _noise("背景", "浅底", "深底")),
            ("甲方", "出发")),
        add("s3_chain_hidden", "dev", "S3", "chain", "schedule", "irreversible", "hidden",
            "没有通知。时间在第一次阅读后会变，提醒必须使用变后的时间。", False,
            (_remind(("r2",), "exact", "clock"),),
            (_todo("工单", "关闭前复核"), _when("clock", "状态页时间", "2026-12-01T09:00:00+08:00", "2026-12-04T09:00:00+08:00")),
            (_todo("合同", "交付前复核"), _when("clock", "合同时间", "2026-12-09T17:00:00+08:00", "2026-12-11T17:00:00+08:00")),
            ("工单", "合同")),
        add("s3_join_hidden", "dev", "S3", "join", "vault+schedule", "irreversible", "hidden",
            "两份时间最初相同，其中一份会悄悄改掉。没有通知时不要用先读到的旧时间创建提醒。", False,
            (_draft("todo", ("r_extra",), ("extra",)), _remind(("r_notes", "r_clock"), "abstain", "clock")),
            (_when("notes", "纪要时间", "2026-12-01T09:00:00+08:00", None), _when("clock", "日程时间", "2026-12-01T09:00:00+08:00", "2026-12-08T09:00:00+08:00"), _todo_as("extra", "待办原文", "整理实验记录")),
            (_when("notes", "邮件时间", "2026-12-05T12:00:00+08:00", None), _when("clock", "表格时间", "2026-12-05T12:00:00+08:00", "2026-12-07T12:00:00+08:00"), _todo_as("extra", "待办原文", "准备验收材料")),
            ("纪要", "邮件")),
        add("s3_parallel_hidden", "val", "S3", "parallel", "vault+schedule", "reversible+irreversible", "hidden",
            "没有通知。草稿保持，提醒必须改用阅读后变掉的时间。", False,
            (_draft("todo", ("r_notes",), ("notes",)), _remind(("r_clock",), "exact", "clock")),
            (_todo("实验记录", "整理实验记录"), _when("clock", "提交时间", "2026-12-01T09:00:00+08:00", "2026-12-04T15:00:00+08:00")),
            (_todo("备份记录", "补齐备份校验"), _when("clock", "备份时间", "2026-12-03T18:00:00+08:00", "2026-12-06T18:00:00+08:00")),
            ("实验", "备份")),
        add("s3_fanout_hidden", "val", "S3", "fanout", "vault+schedule", "reversible+irreversible", "hidden",
            "同一份原文里的待办不变、时间会悄悄变。草稿留待办，提醒用变后的时间。", False,
            (_draft("todo", ("r_notes",), ("notes",)), _remind(("r_notes",), "exact", "notes")),
            (_both("值班纪要", "接听告警", "2026-12-02T08:00:00+08:00", "2026-12-03T08:00:00+08:00"),),
            (_both("发布纪要", "冻结分支", "2026-12-04T20:00:00+08:00", "2026-12-05T20:00:00+08:00"),),
            ("值班", "发布")),
        add("s3_parallel_one_clock", "test", "S3", "parallel", "schedule", "irreversible", "hidden",
            "两份时间独立。只有第二份会悄悄变化，提醒跟第二份的新时间。", False,
            (_draft("first", ("r_notes",), ("notes",)), _remind(("r_extra",), "exact", "extra")),
            (_say("notes", "内部安排", "保持原计划", None, "安排"), _when("extra", "外部时间", "2026-12-02T09:00:00+08:00", "2026-12-12T09:00:00+08:00")),
            (_say("notes", "联调安排", "保持原顺序", None, "安排"), _when("extra", "验收时间", "2026-12-04T09:00:00+08:00", "2026-12-15T09:00:00+08:00")),
            ("内部", "联调")),
        add("s3_chain_forbid", "test", "S3", "chain", "vault", "reversible", "hidden",
            "第二份状态会悄悄变成禁止关闭。草稿必须写下变后的原句，并且不要创建提醒。", False,
            (_draft("status", ("r2",), ("clock",)),),
            (_todo("工单", "关闭前再看"), _say("clock", "状态", "处理中", "不要关闭", "状态")),
            (_todo("巡检", "归档前再看"), _say("clock", "巡检状态", "观察中", "不要归档", "状态")),
            ("工单", "巡检")),
        add("s3_join_converge", "test", "S3", "join", "schedule", "irreversible", "hidden",
            "两份时间会悄悄改成同一个新时间。提醒使用这个新时间，不能沿用任何一份旧时间。", False,
            (_remind(("r_notes", "r_clock"), "exact", "clock"),),
            (_when("notes", "甲方旧时间", "2026-12-01T09:00:00+08:00", "2026-12-06T09:00:00+08:00"), _when("clock", "乙方旧时间", "2026-12-02T09:00:00+08:00", "2026-12-06T09:00:00+08:00")),
            (_when("notes", "出发旧时间", "2026-12-03T08:00:00+08:00", "2026-12-09T08:00:00+08:00"), _when("clock", "集合旧时间", "2026-12-04T08:00:00+08:00", "2026-12-09T08:00:00+08:00")),
            ("甲方", "出发")),
        add("s3_fanout_owner_hidden", "test", "S3", "fanout", "vault", "reversible", "hidden",
            "名单上的负责人会悄悄更换。待办句子保持，负责人备忘使用新名字。", False,
            (_draft("todo", ("r_notes",), ("notes",)), _draft("owner", ("r_notes",), detail_from=("notes",))),
            (_owned("值班名单", "接听告警", "旧值班", "新值班"),),
            (_owned("支持名单", "回复工单", "旧支持", "新支持"),),
            ("值班", "支持")),
        add("s4_join_conflict", "dev", "S4", "join", "vault+schedule", "irreversible", "conflict",
            "两份截止时间从一开始就不同。可以写待办草稿，不要创建提醒。", False,
            (_draft("todo", ("r_extra",), ("extra",)), _remind(("r_notes", "r_clock"), "abstain", "clock")),
            (_when("notes", "纪要时间", "2026-12-01T09:00:00+08:00", None), _when("clock", "日程时间", "2026-12-11T09:00:00+08:00", None), _todo_as("extra", "待办原文", "整理实验记录")),
            (_when("notes", "第一封邮件", "2026-12-02T10:00:00+08:00", None), _when("clock", "第二封邮件", "2026-12-12T10:00:00+08:00", None), _todo_as("extra", "待办原文", "准备验收材料")),
            ("纪要", "邮件")),
        add("s4_chain_missing", "dev", "S4", "chain", "vault", "reversible", "missing",
            "先读事项再读时间栏。时间栏写明还没定，草稿记下事项和「时间未定」，不要创建提醒。", False,
            (_draft("todo", ("r2",), ("notes", "clock")),),
            (_todo("会议纪要", "整理实验记录"), _say("clock", "时间栏", "时间未定", None, "时间")),
            (_todo("聊天摘录", "补一版流程图"), _say("clock", "时间栏", "时间未定", None, "时间")),
            ("纪要", "聊天")),
        add("s4_parallel_partial_time", "val", "S4", "parallel", "vault+schedule", "irreversible", "missing",
            "一份写了待办，另一份明确没有时间。草稿只写待办，不要用空时间创建提醒。", False,
            (_draft("todo", ("r_notes",), ("notes",)), _remind(("r_clock",), "abstain", "clock")),
            (_todo("需求说明", "补齐接口示例"), _say("clock", "排期栏", "时间未定", None, "时间")),
            (_todo("测试说明", "补齐回归用例"), _say("clock", "排期栏", "时间未定", None, "时间")),
            ("需求", "测试")),
        add("s4_fanout_undated", "val", "S4", "fanout", "vault", "reversible", "missing",
            "同一份原文只有待办、没有时间。两段草稿都只写待办，不要创建提醒。", False,
            (_draft("todo", ("r_notes",), ("notes",)), _draft("copy", ("r_notes",), ("notes",))),
            (_todo("讨论记录", "整理实验记录"),),
            (_todo("设计讨论", "补一版流程图"),),
            ("讨论", "设计")),
        add("s4_parallel_owner_conflict", "test", "S4", "parallel", "vault", "reversible", "conflict",
            "两份资料给出不同负责人。草稿要同时保留两个名字，不要合并成一个提醒。", False,
            (_draft("names", ("r_notes",), ("notes",), detail_from=("notes",)), _remind(("r_extra",), "abstain", "extra")),
            (_doc("notes", "名单甲", "负责人甲：林夏。负责人乙：周宁。", None, "林夏", detail="周宁"), _say("extra", "提醒栏", "不要合并", None, "约束")),
            (_doc("notes", "名单乙", "负责人甲：赵衡。负责人乙：陈舟。", None, "赵衡", detail="陈舟"), _say("extra", "提醒栏", "不要合并", None, "约束")),
            ("名单甲", "名单乙")),
        add("s4_chain_void", "test", "S4", "chain", "vault", "reversible", "conflict",
            "第一份给了时间，第二份写明作废。草稿只保留作废原句，不要按第一份时间创建提醒。", False,
            (_draft("void", ("r2",), ("clock",)),),
            (_when("notes", "旧时间", "2026-12-02T10:00:00+08:00", None), _say("clock", "作废说明", "该时间作废", None, "结论")),
            (_when("notes", "旧排期", "2026-12-03T10:00:00+08:00", None), _say("clock", "作废通知", "该排期作废", None, "结论")),
            ("旧时间", "旧排期")),
        add("s4_join_three_way", "test", "S4", "join", "schedule", "irreversible", "conflict",
            "三份时间互不相同。不要创建提醒。", False,
            (_remind(("r_notes", "r_clock", "r_extra"), "abstain", "clock"),),
            (_when("notes", "来源甲", "2026-12-01T09:00:00+08:00", None), _when("clock", "来源乙", "2026-12-02T09:00:00+08:00", None), _when("extra", "来源丙", "2026-12-03T09:00:00+08:00", None)),
            (_when("notes", "渠道甲", "2026-12-04T09:00:00+08:00", None), _when("clock", "渠道乙", "2026-12-05T09:00:00+08:00", None), _when("extra", "渠道丙", "2026-12-06T09:00:00+08:00", None)),
            ("来源", "渠道")),
        add("s4_fanout_no_owner", "test", "S4", "fanout", "vault", "reversible", "missing",
            "原文没有负责人。两段草稿只写待办，不要把候选名单里的人名写进去。", False,
            (_draft("todo", ("r_notes",), ("notes",), must_not_from=("extra",)), _draft("copy", ("r_notes",), ("notes",), must_not_from=("extra",))),
            (_todo("任务说明", "整理实验记录"), _noise("候选名单", "佚名", "佚名")),
            (_todo("任务卡片", "补齐备份校验"), _noise("候选名单", "佚名", "佚名")),
            ("任务说明", "任务卡片")),
        add("s5_parallel_partial", "dev", "S5", "parallel", "vault+schedule", "reversible+irreversible", "partial",
            "待办和附件索引都不变，只有时间变化。前两段保持原文，提醒用新时间。", True,
            (_draft("todo", ("r_notes",), ("notes",)), _draft("index", ("r_extra",), ("extra",)), _remind(("r_clock",), "exact", "clock")),
            (_todo("会议纪要", "整理实验记录"), _say("extra", "附件索引", "已同步", None, "索引"), _when("clock", "截止说明", "2026-12-01T09:00:00+08:00", "2026-12-04T15:00:00+08:00")),
            (_todo("发布单", "更新回滚步骤"), _say("extra", "检查清单", "已勾选", None, "索引"), _when("clock", "上线窗口", "2026-12-03T21:00:00+08:00", "2026-12-05T21:00:00+08:00")),
            ("会议", "发布")),
        add("s5_fanout_partial", "dev", "S5", "fanout", "vault+schedule", "reversible+irreversible", "partial",
            "同一份原文的待办句子不变，只有时间变化。草稿留待办，提醒用新时间。", True,
            (_draft("todo", ("r_notes",), ("notes",)), _remind(("r_notes",), "exact", "notes")),
            (_both("项目纪要", "整理实验记录", "2026-12-01T09:00:00+08:00", "2026-12-06T13:00:00+08:00"),),
            (_both("计划书", "补齐监控", "2026-12-08T16:00:00+08:00", "2026-12-10T16:00:00+08:00"),),
            ("纪要", "计划")),
        add("s5_chain_tail", "val", "S5", "chain", "vault", "reversible", "partial",
            "长链里只有最后一份签核会变。草稿使用变后的签核原句。", True,
            (_draft("signoff", ("r3",), ("tail",)),),
            (_todo("申请单", "开通只读权限"), _say("extra", "安全复查", "没有外联", None, "复查"), _say("tail", "签核", "待审批", "同意开通", "签核")),
            (_todo("账号单", "加入审计组"), _say("extra", "权限复查", "没有写权限", None, "复查"), _say("tail", "审批", "待审批", "同意加入", "签核")),
            ("申请", "账号")),
        add("s5_join_one_side", "val", "S5", "join", "vault+schedule", "irreversible", "partial",
            "索引草稿不能混入新时间。提醒仍要等两侧都读完，并使用变后的时间。", True,
            (_draft("index", ("r_notes",), ("notes",), must_not_from=("clock",)), _remind(("r_notes", "r_clock"), "exact", "clock")),
            (_say("notes", "附件索引", "已同步", None, "索引"), _when("clock", "截止说明", "2026-12-01T09:00:00+08:00", "2026-12-04T15:00:00+08:00")),
            (_say("notes", "检查清单", "已勾选", None, "索引"), _when("clock", "上线窗口", "2026-12-03T21:00:00+08:00", "2026-12-05T21:00:00+08:00")),
            ("附件", "检查")),
        add("s5_parallel_keep_drafts", "test", "S5", "parallel", "vault+schedule", "reversible+irreversible", "partial",
            "预算说明和风险说明都不变，只有付款时间变化。两段说明保持原文，提醒用新时间。", True,
            (_draft("budget", ("r_notes",), ("notes",)), _draft("risk", ("r_extra",), ("extra",)), _remind(("r_clock",), "exact", "clock")),
            (_todo("预算说明", "维持原预算"), _todo_as("extra", "风险说明", "维持原风险"), _when("clock", "付款时间", "2026-12-06T12:00:00+08:00", "2026-12-08T12:00:00+08:00")),
            (_todo("报价说明", "维持原报价"), _todo_as("extra", "条款说明", "维持原条款"), _when("clock", "签约时间", "2026-12-07T12:00:00+08:00", "2026-12-09T12:00:00+08:00")),
            ("预算", "报价")),
        add("s5_fanout_one_field", "test", "S5", "fanout", "vault", "reversible", "partial",
            "同一份名单只更换负责人。待办草稿不能写入新名字，负责人备忘必须使用新名字。", True,
            (_draft("todo", ("r_notes",), ("notes",), must_not_from=("notes",)), _draft("owner", ("r_notes",), detail_from=("notes",))),
            (_doc("notes", "值班名单", "待办：接听告警。负责人：旧值班。", "待办：接听告警。负责人：新值班。", "接听告警", "旧值班", "新值班", "新值班"),),
            (_doc("notes", "支持名单", "待办：回复工单。负责人：旧支持。", "待办：回复工单。负责人：新支持。", "回复工单", "旧支持", "新支持", "新支持"),),
            ("值班", "支持")),
        add("s5_chain_keep_early", "test", "S5", "chain", "vault+schedule", "reversible+irreversible", "partial",
            "前面的事项草稿保持不变。提醒依赖链尾，并使用变后的时间。", True,
            (_draft("early", ("r_notes",), ("notes",)), _remind(("r2",), "exact", "clock")),
            (_todo("事项", "整理实验记录"), _when("clock", "链尾时间", "2026-12-01T09:00:00+08:00", "2026-12-04T15:00:00+08:00")),
            (_todo("步骤", "补齐备份校验"), _when("clock", "链尾排期", "2026-12-03T18:00:00+08:00", "2026-12-06T18:00:00+08:00")),
            ("事项", "步骤")),
        add("s5_join_abstain_keep_draft", "test", "S5", "join", "vault+schedule", "irreversible", "partial",
            "待办草稿保持。时间一侧变化后两份时间不再一致，这时不要创建提醒。", True,
            (_draft("todo", ("r_extra",), ("extra",)), _remind(("r_notes", "r_clock"), "abstain", "clock")),
            (_when("notes", "纪要时间", "2026-12-01T09:00:00+08:00", None), _when("clock", "日程时间", "2026-12-01T09:00:00+08:00", "2026-12-08T09:00:00+08:00"), _todo_as("extra", "待办原文", "整理实验记录")),
            (_when("notes", "邮件时间", "2026-12-05T12:00:00+08:00", None), _when("clock", "表格时间", "2026-12-05T12:00:00+08:00", "2026-12-07T12:00:00+08:00"), _todo_as("extra", "待办原文", "准备验收材料")),
            ("纪要", "邮件")),
    ]
    if len(rows) != 48:
        raise RuntimeError(f"蓝图数量是 {len(rows)}，不是 48")
    return tuple(rows)


def _noise(title: str, old: str, new: str) -> Source:
    return _doc("extra", title, old, new, "", old, new)


def _noise_as(sid: str, title: str, old: str, new: str) -> Source:
    return _doc(sid, title, old, new, "", old, new)


def all_tasks() -> list[dict]:
    rows: list[dict] = []
    for spec in SPECS:
        rows.extend(spec.instances())
    return rows


SPECS = build_catalog()
