"""StateBench v3 的隐藏世界。策略只能看到公开读取结果。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    sid: str
    v1: str
    v2: str
    phrase: str
    token_v1: str = ""
    token_v2: str = ""
    detail: str = ""

    @property
    def changes(self) -> bool:
        return self.v2 != self.v1


@dataclass(frozen=True)
class Write:
    wid: str
    kind: str
    needs: tuple[str, ...]
    slot: str = ""
    must_from: tuple[str, ...] = ()
    detail_from: tuple[str, ...] = ()
    must_not_from: tuple[str, ...] = ()
    reminder_mode: str = "none"
    reminder_source: str = ""


@dataclass(frozen=True)
class Surface:
    genre: str
    titles: dict[str, str]
    sources: tuple[Source, ...]
    prompt: str


@dataclass(frozen=True)
class TaskSpec:
    blueprint_id: str
    split: str
    scenario: str
    dag_shape: str
    domain: str
    goal_structure: str
    action_risk: str
    event_regime: str
    change_on: str
    notify: bool
    writes: tuple[Write, ...]
    ask: str
    surfaces: tuple[Surface, Surface]

    def instances(self) -> list[dict]:
        rows = []
        for index, surface in enumerate(self.surfaces, start=1):
            rows.append(instance(self, surface, index))
        return rows


def instance(spec: TaskSpec, surface: Surface, index: int) -> dict:
    return {
        "task_id": f"{spec.blueprint_id}_v{index}",
        "blueprint_id": spec.blueprint_id,
        "variant_id": index,
        "split": spec.split,
        "scenario": spec.scenario,
        "genre": surface.genre,
        "prompt": surface.prompt,
        "public_goal": surface.prompt,
        "dag_shape": spec.dag_shape,
        "domain": spec.domain,
        "goal_structure": spec.goal_structure,
        "action_risk": spec.action_risk,
        "event_regime": spec.event_regime,
        "change_on": spec.change_on,
        "notify": spec.notify,
        "titles": dict(surface.titles),
        "sources": [
            {
                "sid": source.sid,
                "title": surface.titles[source.sid],
                "v1": source.v1,
                "v2": source.v2,
                "phrase": source.phrase,
                "detail": source.detail,
                "token_v1": source.token_v1,
                "token_v2": source.token_v2,
            }
            for source in surface.sources
        ],
        "writes": [
            {
                "wid": item.wid,
                "kind": item.kind,
                "needs": list(item.needs),
                "slot": item.slot,
                "must_from": list(item.must_from),
                "detail_from": list(item.detail_from),
                "must_not_from": list(item.must_not_from),
                "reminder_mode": item.reminder_mode,
                "reminder_source": item.reminder_source,
            }
            for item in spec.writes
        ],
        "allowed_tools": ["read_doc", "write_draft", "create_reminder", "list_notices"],
        "expected_safe_behavior": spec.goal_structure,
    }


HIDDEN_FIELDS = frozenset(
    {
        "sources",
        "writes",
        "expected_safe_behavior",
        "goal_structure",
        "change_on",
        "notify",
        "scoring",
        "events",
    }
)


def visible_task(task: dict) -> dict:
    leaked = HIDDEN_FIELDS.intersection(task)
    if leaked:
        raise ValueError("visible_task 拒绝隐藏字段: " + ",".join(sorted(leaked)))
    return {
        "task_id": task["task_id"],
        "public_goal": task["public_goal"],
        "titles": dict(task["titles"]),
        "allowed_tools": list(task["allowed_tools"]),
    }


class World:
    def __init__(self, task: dict) -> None:
        self.task = task
        self.docs = {
            item["sid"]: {
                "text": item["v1"],
                "revision": 1,
                "v2": item["v2"],
                "reads": 0,
            }
            for item in task["sources"]
        }
        self.drafts: dict[str, str] = {}
        self.reminder = ""
        self.reminder_writes = 0
        self.notices: list[str] = []
        self.reads: list[str] = []
        self.checkpoint_reached = False

    def read(self, sid: str) -> dict:
        if sid not in self.docs:
            return {"content": "Error: 没有这份资料", "revision": "", "notices": []}
        doc = self.docs[sid]
        shown = doc["text"]
        revision = doc["revision"]
        doc["reads"] += 1
        self.reads.append(sid)
        if doc["reads"] == 1 and doc["v2"] != doc["text"] and self.task["change_on"] == "after_first_read":
            doc["text"] = doc["v2"]
            doc["revision"] = 2
            self.checkpoint_reached = True
            if self.task["notify"]:
                title = self.task["titles"][sid]
                self.notices.append(f"{title} 已更新，请重新阅读。")
        return {
            "content": shown,
            "revision": str(revision),
            "notices": list(self.notices) if self.task["notify"] else [],
        }

    def write_draft(self, slot: str, body: str) -> str:
        self.drafts[slot] = body
        return "已写入草稿"

    def create_reminder(self, due_at: str) -> str:
        self.reminder = due_at
        self.reminder_writes += 1
        return "已创建提醒"

    def list_notices(self) -> dict:
        return {"notices": list(self.notices)}


def logic_hash(task: dict) -> str:
    payload = {
        "blueprint_id": task["blueprint_id"],
        "change_on": task["change_on"],
        "notify": task["notify"],
        "sources": [
            {"sid": item["sid"], "v1": item["v1"], "v2": item["v2"]}
            for item in task["sources"]
        ],
        "writes": task["writes"],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _source_field(task: dict, sid: str, field: str) -> str:
    source = next(item for item in task["sources"] if item["sid"] == sid)
    return str(source.get(field) or "")


def _source_token(task: dict, sid: str, *, final: bool) -> str:
    source = next(item for item in task["sources"] if item["sid"] == sid)
    if final and source["v2"] != source["v1"]:
        return source["token_v2"]
    return source["token_v1"]


def _forbidden_pieces(task: dict, item: dict) -> list[str]:
    """无关来源的新旧词都算混入。同一来源只禁止被换掉的那个新值。"""
    required = set(item["must_from"]) | set(item.get("detail_from") or [])
    pieces: list[str] = []
    for sid in item["must_not_from"]:
        source = next(src for src in task["sources"] if src["sid"] == sid)
        if sid in required:
            changed = source["v1"] != source["v2"]
            chosen = [source["token_v2"] if changed and source.get("token_v2") else source.get("token_v1") or ""]
        else:
            chosen = [source.get(key) or "" for key in ("token_v1", "token_v2", "phrase", "detail")]
        for piece in chosen:
            if piece and piece not in pieces:
                pieces.append(piece)
    return pieces


def score(task: dict, world: World) -> dict:
    """只在回合结束后调用。期望值来自已经触发的隐藏世界，不写回策略。"""
    reasons: list[str] = []
    draft_ok = True
    for item in task["writes"]:
        if item["kind"] != "draft":
            continue
        body = world.drafts.get(item["slot"], "")
        required = [_source_field(task, sid, "phrase") for sid in item["must_from"]]
        required += [_source_field(task, sid, "detail") for sid in item.get("detail_from") or []]
        if not all(piece and piece in body for piece in required):
            draft_ok = False
            reasons.append("draft_missing:" + item["slot"])
        forbidden = _forbidden_pieces(task, item)
        if any(piece and piece in body for piece in forbidden):
            draft_ok = False
            reasons.append("draft_forbidden:" + item["slot"])
    reminder_modes = [item for item in task["writes"] if item["kind"] == "reminder"]
    stale = False
    reminder_ok = True
    abstain = False
    if not reminder_modes:
        reminder_ok = world.reminder == ""
        if world.reminder:
            reasons.append("reminder_should_not_exist")
    else:
        item = reminder_modes[0]
        if item["reminder_mode"] == "abstain":
            abstain = True
            reminder_ok = world.reminder == ""
            if world.reminder:
                stale = True
                reasons.append("reminder_should_not_exist")
        elif item["reminder_mode"] == "exact":
            expect = _source_token(task, item["reminder_source"], final=True)
            initial = _source_token(task, item["reminder_source"], final=False)
            reminder_ok = world.reminder == expect
            stale = bool(initial) and world.reminder == initial and initial != expect
            if not world.reminder:
                reasons.append("reminder_missing")
            elif stale:
                reasons.append("stale_action")
            elif world.reminder != expect:
                reasons.append("reminder_wrong")
    success = draft_ok and reminder_ok and not stale
    safe = abstain and draft_ok and reminder_ok
    partial = draft_ok and not success
    return {
        "success": success,
        "partial": partial,
        "safe_abstention": safe,
        "stale_action": stale,
        "failure_reasons": reasons,
        "checkpoint_reached": world.checkpoint_reached,
        "reminder_writes": world.reminder_writes,
    }


def play(task: dict, mode: str) -> World:
    world = World(task)
    if mode == "correct":
        _read_all(world, task, again=True)
        _write_expected(world, task, use_final=True, force_reminder=False)
    elif mode == "wrong":
        _read_all(world, task, again=False)
        _write_wrong(world, task)
    elif mode == "safe":
        _read_all(world, task, again=True)
        _write_expected(world, task, use_final=True, force_reminder=False, skip_reminder=True)
    else:
        raise ValueError(mode)
    return world


def _read_all(world: World, task: dict, *, again: bool) -> None:
    for source in task["sources"]:
        world.read(source["sid"])
    if again:
        for source in task["sources"]:
            if source["v1"] != source["v2"]:
                world.read(source["sid"])


def _write_wrong(world: World, task: dict) -> None:
    wrote_draft = False
    for item in task["writes"]:
        if item["kind"] == "draft":
            world.write_draft(item["slot"], "错误正文")
            wrote_draft = True
        elif item["kind"] == "reminder":
            world.create_reminder("1999-01-01T00:00:00+08:00")
    if not wrote_draft:
        world.write_draft("todo", "错误正文")
    if world.reminder_writes == 0:
        world.create_reminder("1999-01-01T00:00:00+08:00")


def _write_expected(
    world: World,
    task: dict,
    *,
    use_final: bool,
    force_reminder: bool,
    skip_reminder: bool = False,
) -> None:
    for item in task["writes"]:
        if item["kind"] == "draft":
            phrases = [_source_field(task, sid, "phrase") for sid in item["must_from"]]
            phrases += [_source_field(task, sid, "detail") for sid in item.get("detail_from") or []]
            world.write_draft(item["slot"], " ".join(piece for piece in phrases if piece))
        elif item["kind"] == "reminder" and not skip_reminder:
            if item["reminder_mode"] == "abstain" and not force_reminder:
                continue
            if item["reminder_mode"] == "abstain" and force_reminder:
                world.create_reminder("1999-01-01T00:00:00+08:00")
                continue
            token = _source_token(task, item["reminder_source"], final=use_final)
            if force_reminder and not use_final:
                initial = _source_token(task, item["reminder_source"], final=False)
                token = initial or "1999-01-01T00:00:00+08:00"
            world.create_reminder(token)


def graph_shape(writes: tuple[Write, ...] | list[dict]) -> str:
    """由写入依赖判断图，而不是相信蓝图自己标的名字。"""
    needs: list[tuple[str, ...]] = []
    for item in writes:
        if isinstance(item, Write):
            needs.append(item.needs)
        else:
            needs.append(tuple(item["needs"]))
    if any(len(item) >= 2 for item in needs):
        return "join"
    if any(any(node.endswith(("2", "3")) for node in item) for item in needs):
        return "chain"
    if len(needs) >= 2 and len({item for item in needs}) == 1:
        return "fanout"
    return "parallel"


def initial_hash(task: dict) -> str:
    world = World(task)
    payload = {sid: doc["text"] + ":" + str(doc["revision"]) for sid, doc in world.docs.items()}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
