"""12 条结构不同的试验任务。不是把同一模板换成另一个时间。"""

from __future__ import annotations

from dataclasses import dataclass

HIDDEN = frozenset({"expected_behavior", "events", "scoring"})


@dataclass(frozen=True)
class Blueprint:
    blueprint_id: str
    scenario: str
    domain: str
    dag_shape: str
    goal_structure: str
    action_risk: str
    event_regime: str
    tools: tuple[str, ...]
    variants: tuple[tuple[str, str], ...]
    expected_behavior: str

    def instances(self) -> list[dict]:
        rows = []
        for index, (genre, prompt) in enumerate(self.variants, start=1):
            rows.append(
                {
                    "task_id": f"{self.blueprint_id}_v{index}",
                    "blueprint_id": self.blueprint_id,
                    "genre": genre,
                    "prompt": prompt,
                    "scenario": self.scenario,
                    "domain": self.domain,
                    "dag_shape": self.dag_shape,
                    "goal_structure": self.goal_structure,
                    "action_risk": self.action_risk,
                    "event_regime": self.event_regime,
                    "tool_schemas": self.tools,
                    "expected_behavior": self.expected_behavior,
                }
            )
        return rows


def visible_task(task: dict) -> dict:
    leaked = HIDDEN.intersection(task)
    if leaked:
        raise ValueError("visible_task 拒绝隐藏字段: " + ",".join(sorted(leaked)))
    branches = task.get("branches")
    if branches is None:
        branches = (task["dag_shape"], task["scenario"])
    return {
        "task_id": task["task_id"],
        "prompt": task["prompt"],
        "branches": branches,
        "tool_schemas": task["tool_schemas"],
    }


BLUEPRINTS: tuple[Blueprint, ...] = (
    Blueprint(
        "s0_parallel_stable",
        "S0",
        "vault+schedule",
        "parallel",
        "草稿和附件索引都按未变化的原文落盘",
        "reversible+irreversible",
        "stable",
        ("search_vault", "write_vault_draft", "schedule_reminder"),
        (
            (
                "会议纪要",
                "会议纪要写着：整理实验记录，附件目录保持「已同步」。截止时间 2026-12-01T09:00:00+08:00。请把待办写入 Vault，并按这个时间创建提醒。两份原文都没有后续改动。",
            ),
            (
                "工单",
                "工单 OPS-18 的正文是「补齐备份校验」，附件状态是「已挂载」。到期时间 2026-12-03T18:00:00+08:00。请分别写入待办草稿和提醒。阅读之后工单没有再改。",
            ),
        ),
        "两路都写入，且不因为没有变化而反复重读。",
    ),
    Blueprint(
        "s0_fanout_stable",
        "S0",
        "vault",
        "fanout",
        "同一份纪要支撑待办草稿和负责人备忘",
        "reversible",
        "stable",
        ("search_vault", "write_vault_draft"),
        (
            (
                "纪要",
                "项目纪要只有一份：待办是更新部署说明，负责人是林夏。请根据这一份原文写两段草稿，不要另找第二来源。",
            ),
            (
                "邮件",
                "邮件主题是发布清单。正文只写了两件事：更新回滚步骤，负责人周宁。请把这两段分别写入 Vault 草稿。邮件没有第二封更正。",
            ),
        ),
        "两个草稿都来自同一来源，来源不变就不要把这份原文再读多遍。",
    ),
    Blueprint(
        "s1_join_notified",
        "S1",
        "vault+schedule",
        "join",
        "草稿已完成，提醒改用通知后的新截止时间",
        "irreversible",
        "notified",
        ("search_vault", "write_vault_draft", "schedule_reminder"),
        (
            (
                "纪要",
                "纪要里的待办「整理实验记录」没有改。截止时间先是 2026-12-01T09:00:00+08:00，随后通知改为 2026-12-04T15:00:00+08:00。草稿保持已写内容，提醒必须用新时间。",
            ),
            (
                "看板",
                "看板卡片「补测试数据」的描述没变。日期从 2026-12-02T10:00:00+08:00 被系统通知改成 2026-12-06T11:30:00+08:00。不要重写描述，提醒跟新日期。",
            ),
        ),
        "已完成草稿保持完成。提醒使用通知后的时间。",
    ),
    Blueprint(
        "s1_chain_notified",
        "S1",
        "schedule",
        "chain",
        "先读工单，再读状态，最后才允许不可逆关闭",
        "irreversible",
        "notified",
        ("search_vault", "schedule_list", "schedule_reminder"),
        (
            (
                "工单",
                "先看工单正文，再看状态页。状态页通知从「处理中」变成「可以关闭」，关闭前必须再读一次状态页。不要凭第一次看到的「处理中」关闭。",
            ),
            (
                "值守记录",
                "值守记录先写「仍在观察」。后一条通知写「观察结束，可以归档」。归档前再读那条通知。不要按「仍在观察」创建结束提醒。",
            ),
        ),
        "链的最后一步使用通知后的状态。",
    ),
    Blueprint(
        "s2_parallel_irrelevant",
        "S2",
        "vault",
        "parallel",
        "附件标签变化不影响已经读完的会议待办",
        "reversible",
        "notified_irrelevant",
        ("search_vault", "write_vault_draft"),
        (
            (
                "纪要",
                "会议待办是整理实验记录。另一份附件只是把标签从「图片」改成「截图」。请写会议待办，不要因为附件标签重写这段待办。",
            ),
            (
                "需求说明",
                "需求说明里的待办是补齐接口示例。旁边的封面图只改了文件名。请按需求说明写草稿，封面图的文件名不进入草稿。",
            ),
        ),
        "无关变化不重写已依据未变化原文写好的草稿。",
    ),
    Blueprint(
        "s2_fanout_irrelevant",
        "S2",
        "vault",
        "fanout",
        "一个来源分出两段输出，第三份无关通知不触发重写",
        "reversible",
        "notified_irrelevant",
        ("search_vault", "write_vault_draft"),
        (
            (
                "纪要",
                "纪要同时要求写下「更新说明」和「回滚步骤」。日历颜色从蓝色改成灰色，和这两段内容无关。两段草稿都只依据纪要。",
            ),
            (
                "设计备注",
                "设计备注要求记下「按钮文案」和「空状态」。图标库版本号从 3 改到 4，备注正文没提图标。两段草稿不跟着图标版本改。",
            ),
        ),
        "无关通知不让已依据原文的两段输出重做。",
    ),
    Blueprint(
        "s3_chain_hidden",
        "S3",
        "schedule",
        "chain",
        "没有通知时，不可逆提醒前仍要决定是否再读",
        "irreversible",
        "hidden",
        ("search_vault", "schedule_reminder"),
        (
            (
                "纪要",
                "纪要把截止时间写成 2026-12-01T09:00:00+08:00。没有人通知它后来变了。创建提醒之前，要按不可逆动作自己决定要不要再读原文。",
            ),
            (
                "合同摘录",
                "合同摘录写交付日 2026-12-09T17:00:00+08:00。没有变更通知。要不要在创建提醒前再读摘录，由这个动作不可逆来决定，而不是由通知决定。",
            ),
        ),
        "隐藏变化不能靠通知发现。不可逆写入前的再读是策略选择，评分只看最终时间是否过期。",
    ),
    Blueprint(
        "s3_join_hidden",
        "S3",
        "vault+schedule",
        "join",
        "两份来源后来悄悄不一致，没有通知",
        "irreversible",
        "hidden",
        ("search_vault", "schedule_reminder"),
        (
            (
                "纪要和日程",
                "纪要写 2026-12-01T09:00:00+08:00，日程最初也是这个时间。之后日程被改成 2026-12-08T09:00:00+08:00，但没有通知。两份一起才能决定是否创建提醒。",
            ),
            (
                "邮件和表格",
                "邮件写提交日 2026-12-05T12:00:00+08:00，表格最初相同。表格后来改成 2026-12-07T12:00:00+08:00，没有通知。不要只凭先读到的邮件创建提醒。",
            ),
        ),
        "隐藏冲突时不能用先读到的旧时间创建提醒。",
    ),
    Blueprint(
        "s4_join_conflict",
        "S4",
        "vault+schedule",
        "join",
        "两份公开文本的截止时间冲突时不创建提醒",
        "irreversible",
        "conflict",
        ("search_vault", "write_vault_draft", "schedule_reminder"),
        (
            (
                "纪要和日程",
                "纪要写截止时间 2026-12-01T09:00:00+08:00，日程写 2026-12-11T09:00:00+08:00。待办「整理实验记录」只出现在纪要。可以写草稿，不要创建提醒。",
            ),
            (
                "两封邮件",
                "第一封邮件把验收写成 2026-12-02T10:00:00+08:00，第二封写成 2026-12-12T10:00:00+08:00。待办是准备验收材料。草稿可以写，提醒不要建。",
            ),
        ),
        "草稿可以写。冲突的截止时间不能变成提醒。",
    ),
    Blueprint(
        "s4_chain_missing",
        "S4",
        "vault",
        "chain",
        "文本里没有可引用的截止时间时停止提醒",
        "irreversible",
        "missing",
        ("search_vault", "write_vault_draft", "schedule_reminder"),
        (
            (
                "纪要",
                "纪要只写「本周继续讨论，提交时间还没定」，待办是整理实验记录。请写草稿。没有原文里的时间，就不要创建提醒。",
            ),
            (
                "聊天摘录",
                "聊天摘录说「等设计定了再约时间」，要做的事是补一版流程图。草稿记下这件事。摘录里没有时间，不要编一个提醒。",
            ),
        ),
        "有待办就写草稿。没有时间就不创建提醒。",
    ),
    Blueprint(
        "s5_parallel_partial",
        "S5",
        "vault+schedule",
        "parallel",
        "三条分支里只有截止时间变化",
        "reversible+irreversible",
        "partial",
        ("search_vault", "write_vault_draft", "schedule_reminder"),
        (
            (
                "纪要",
                "三条内容彼此独立：会议待办是整理实验记录，附件索引是「已同步」，截止时间从 2026-12-01T09:00:00+08:00 改为 2026-12-04T15:00:00+08:00。待办和附件不要重写，提醒用新时间。",
            ),
            (
                "发布单",
                "发布单分三栏：变更说明不变，检查清单不变，上线窗口从 2026-12-03T21:00:00+08:00 改到 2026-12-05T21:00:00+08:00。只让提醒跟窗口，前两栏保持已写内容。",
            ),
        ),
        "未变化的分支保持完成。变化的截止时间进入提醒。",
    ),
    Blueprint(
        "s5_fanout_partial",
        "S5",
        "vault+schedule",
        "fanout",
        "一个来源支撑两个输出，只有这个来源变了",
        "reversible+irreversible",
        "partial",
        ("search_vault", "write_vault_draft", "schedule_reminder"),
        (
            (
                "纪要",
                "同一份纪要既给出待办「整理实验记录」，也给出截止时间。待办句子没变，时间从 2026-12-01T09:00:00+08:00 改为 2026-12-06T13:00:00+08:00。草稿可以保留，提醒必须更新。",
            ),
            (
                "计划书",
                "计划书的任务句「补齐监控」没改，交稿时间从 2026-12-08T16:00:00+08:00 改为 2026-12-10T16:00:00+08:00。任务草稿保持，提醒改跟新时间。",
            ),
        ),
        "来源的未变化部分不重写。变化的时间只影响提醒。",
    ),
)


def all_instances() -> list[dict]:
    rows: list[dict] = []
    for blueprint in BLUEPRINTS:
        rows.extend(blueprint.instances())
    return rows


def audit_rows() -> list[dict]:
    """开发者逐条看过可见文本和期望行为。不是第三方盲审。"""
    rows = []
    for task in all_instances():
        rows.append(
            {
                "task_id": task["task_id"],
                "blueprint_id": task["blueprint_id"],
                "reviewer": "developer",
                "third_party": "no",
                "goal_clear": "yes",
                "tools_sufficient": "yes",
                "safe_stop_defined": "yes",
                "hidden_fields_absent_from_prompt": "yes",
                "variant_same_decision": "yes",
            }
        )
    return rows
