"""模型提出计划，校验器决定能不能执行。失败时不替换成写好的模板。"""

from __future__ import annotations

import json
import re

from collections.abc import Mapping

from agent.algorithms.planner import PlanError, plan_errors
from agent.algorithms.repair import RepairResult, repair_plan
from agent.algorithms.types import PlanNode
from agent.core.model_step import model_step

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def compile_model_plan(prompt: str, *, schema_hint: str, compact: bool = False) -> list[PlanNode]:
    """最多两次模型请求：第一次生成，JSON 或图不合法时把错误发回去再要一次。

    compact 只收紧输出格式，不降低 max_tokens，也不删掉依赖、权限和不可逆标记。
    """
    compact_rule = (
        "只输出 JSON，字段只保留 id、action、args、depends_on_nodes、requires_evidence、irreversible。"
        if compact
        else "你只输出一个 JSON 对象，不要解释。"
    )
    messages = [
        {
            "role": "system",
            "content": (
                compact_rule
                + "计划必须能被校验器接受：动作只有 read_fact 和 write_fact，"
                "依赖无环，写入节点用 value_from 指向已读事实，不可逆写入把 irreversible 设为 true。"
            ),
        },
        {"role": "user", "content": prompt + "\n\n" + schema_hint},
    ]
    error = ""
    for _ in range(2):
        if error:
            messages.append({"role": "user", "content": "上次计划不合法：" + error + "。请只重发 JSON。"})
        from agent.core.llm import usage_phase

        phase = usage_phase.set("plan")
        try:
            raw = model_step(messages, tools=None, max_tokens=4000, temperature=0)
        finally:
            usage_phase.reset(phase)
        text = _response_text(raw)
        messages.append({"role": "assistant", "content": text})
        try:
            return _nodes_from_text(text)
        except (PlanError, ValueError, KeyError, TypeError) as exc:
            error = str(exc)
    raise PlanError(error or "plan_rejected")


def _response_text(raw: dict) -> str:
    """优先使用正式回复。推理字段里出现 JSON 时也读，避免预算耗在推理上就被当成没输出。"""
    content = str(raw.get("content") or "")
    if "{" in content:
        return content
    reasoning = str(raw.get("reasoning_content") or "")
    if "{" in reasoning:
        return reasoning
    return content


def _nodes_from_text(text: str) -> list[PlanNode]:
    matched = _FENCE.search(text)
    body = matched.group(1) if matched else text
    start = body.find("{")
    end = body.rfind("}")
    if start < 0 or end < start:
        raise PlanError("no_json")
    payload = json.loads(body[start : end + 1])
    raw_nodes = payload.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise PlanError("empty_plan")
    nodes: list[PlanNode] = []
    for item in raw_nodes:
        if not isinstance(item, dict):
            raise PlanError("bad_node")
        nodes.append(
            PlanNode(
                str(item.get("id") or ""),
                str(item.get("action") or ""),
                args=dict(item.get("args") or {}),
                depends_on_nodes=[str(dep) for dep in item.get("depends_on_nodes") or []],
                requires_evidence=[str(ev) for ev in item.get("requires_evidence") or []],
                irreversible=bool(item.get("irreversible")),
            )
        )
    for node in nodes:
        if node.action != "write_fact":
            continue
        source = node.args.get("value_from")
        if not isinstance(source, dict) or not source.get("fact_key"):
            raise PlanError("missing_value_from:" + node.id)
    validation = plan_errors(nodes)
    if not validation.valid:
        raise PlanError(validation.error_code + ":" + ",".join(validation.details))
    return nodes


def local_or_full_update(
    nodes: list[PlanNode],
    targets: list[str] | tuple[str, ...],
    public_view: Mapping,
    replacements: dict[str, PlanNode] | None = None,
    *,
    confirmed_writes: tuple[str, ...] = (),
) -> RepairResult:
    """先改未执行子图。局部结果不合法时才整图重编译。已完成节点由 repair_plan 保留。"""
    local = repair_plan(
        nodes,
        targets,
        public_view,
        "local",
        replacements=replacements,
        confirmed_writes=confirmed_writes,
    )
    if local.mode == "stopped" or local.degraded:
        return repair_plan(nodes, targets, public_view, "full", confirmed_writes=confirmed_writes)
    return local
