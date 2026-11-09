"""B0：直接调用 agent_loop。默认脚本模型，只有显式 live 才请求模型。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

import yaml

from agent.core import loop as loop_mod
from evals.statebench.catalog import load_task
from evals.statebench.environment import Environment
from evals.statebench.episode import Episode, build_tools, interpret_usage, scripted_reply
from evals.statebench.scorer import score_episode
from evals.statebench.traces import TraceWriter

ROOT = Path(__file__).resolve().parent
EXPERIMENT_PATH = ROOT / "experiment.yaml"
RUNS = ROOT / "runs"
SYSTEM = "你是状态任务执行器。只能使用 read_fact、write_fact、list_facts。写入值必须来自已经返回的读取结果。"


def load_experiment() -> dict[str, Any]:
    return yaml.safe_load(EXPERIMENT_PATH.read_text(encoding="utf-8"))


def resolve_llm(explicit: str | None = None) -> str:
    if explicit in {"mock", "live"}:
        return explicit
    return "live" if os.environ.get("STATEBENCH_LLM") == "live" else "mock"


@contextmanager
def _decision_hook(episode: Episode) -> Iterator[None]:
    original = loop_mod.inject_background_results

    def inject(messages: list[dict[str, Any]]) -> int:
        count = original(messages)
        episode.before_decision(messages)
        return count

    with patch.object(loop_mod, "inject_background_results", inject):
        yield


def run_b0(
    task_id: str,
    *,
    llm: str | None = None,
    task: dict[str, Any] | None = None,
    workspace: str | Path | None = None,
    trace_dir: str | Path | None = None,
) -> dict[str, Any]:
    experiment = load_experiment()
    mode = resolve_llm(llm)
    spec = json.loads(json.dumps(task if task is not None else load_task(task_id), ensure_ascii=False))
    if workspace is None and trace_dir is None:
        base = RUNS / task_id / datetime.now().strftime("%Y%m%d%H%M%S%f")
    elif workspace is None:
        base = Path(tempfile.mkdtemp(prefix="statebench-run-"))
    else:
        base = Path(workspace)
    base.mkdir(parents=True, exist_ok=True)
    traces = TraceWriter(trace_dir or (base / "traces"))
    env = Environment(
        spec["initial_facts"],
        spec.get("events") or [],
        base / "world",
        readable=spec.get("readable"),
        writable=spec.get("writable"),
        env_only=spec.get("env_only"),
    )
    snapshot_before = env.snapshot_token()
    episode = Episode(spec, env, traces, llm=mode)
    budget = int((experiment.get("budget") or {}).get("max_tool_calls") or 8)
    tools, handlers = build_tools(episode, budget=budget)
    allowed = set(experiment.get("tool_whitelist") or [])
    if allowed and set(handlers) - allowed:
        raise RuntimeError("工具超出白名单")
    messages: list[dict[str, Any]] = [{"role": "user", "content": spec["prompt"]}]

    def system_provider(_messages: list[dict[str, Any]]) -> str:
        return SYSTEM

    def mock_chat(messages: list[dict[str, Any]], tools: list | None = None, max_tokens: int = 5000, **kwargs: Any):
        episode.note_decision(messages)
        reply = scripted_reply(messages, tools=tools, max_tokens=max_tokens, **kwargs)
        episode.record_model(
            reply,
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            usage_source="mock",
            request={"llm": "mock", "temperature": experiment.get("temperature"), "max_tokens": max_tokens},
        )
        return reply

    def live_chat(messages: list[dict[str, Any]], tools: list | None = None, max_tokens: int = 5000, **kwargs: Any):
        from agent.config import MODEL_NAME
        from agent.core.llm import set_usage_hook

        episode.note_decision(messages)
        captured: dict[str, Any] = {"usage": None}

        def hook(usage: dict[str, Any]) -> None:
            captured["usage"] = usage

        set_usage_hook(hook)
        try:
            raw = original_chat(messages, tools=tools, max_tokens=max_tokens, **kwargs)
        finally:
            set_usage_hook(None)
        usage, usage_source = interpret_usage(captured["usage"])
        episode.record_model(
            raw,
            usage=usage,
            usage_source=usage_source,
            request={
                "model": MODEL_NAME,
                "temperature": experiment.get("temperature"),
                "max_tokens": max_tokens,
                "tool_names": [item["function"]["name"] for item in tools or []],
            },
        )
        return raw

    original_chat = loop_mod.chat
    text: str | None = None
    try:
        with _decision_hook(episode):
            chat = mock_chat if mode == "mock" else live_chat
            with patch.object(loop_mod, "chat", chat):
                text = loop_mod.agent_loop(
                    messages,
                    spec.get("prompt") or "",
                    tools=tools,
                    handlers=handlers,
                    system_provider=system_provider,
                    use_mcp=False,
                    extract_memory=False,
                    todo_reminder=False,
                    max_rounds=int(experiment.get("max_rounds") or 6),
                )
    except Exception as exc:
        episode.traces.agent({"kind": "error", "error": str(exc), "termination_reason": "error"})
        raise
    reason = "max_rounds" if text and "处理轮次过多" in text else "completed"
    episode.finish(text, reason=reason)
    score = score_episode(
        spec,
        env,
        episode.writes,
        checkpoint_reached=episode.checkpoint_applied,
        invalidation_log=None,
    )
    episode.traces.world({"kind": "score", **score})
    return {
        "task_id": spec["task_id"],
        "llm": mode,
        "text": text,
        "score": score,
        "trace_dir": str(traces.directory),
        "tool_names": list(episode.tool_names),
        "decision_inputs": episode.decision_inputs,
        "messages": messages,
        "env": env,
        "writes": episode.writes,
        "snapshot_before": snapshot_before,
        "snapshot_after": env.snapshot_token(),
        "blueprint_id": spec.get("blueprint_id"),
        "scene": spec.get("scene"),
        "policy": "B0",
        "plan_hash": "",
        "tool_calls": episode.tool_calls,
        "decision_count": len(episode.decision_inputs),
        "observe_count": sum(1 for name in episode.tool_names if name == "read_fact"),
        "replan_count": 0,
        "degrade_count": 0,
        "rejected_local": 0,
        "unverified_effect_count": 0,
        "recovery_stop_count": 0,
        "evidence_actions": sum(1 for name in episode.tool_names if name == "write_fact"),
        "decisions": [],
        "repair_kinds": [],
        "replans": [],
        "ages": [],
        "goal_verified_final": False,
        "termination_reason": reason,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.statebench.b0")
    parser.add_argument("--task", required=True)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)
    if args.mock and args.live:
        print("mock 与 live 只能选一个", file=sys.stderr)
        return 2
    mode = "mock" if args.mock else "live" if args.live else None
    try:
        result = run_b0(args.task, llm=mode)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(result["trace_dir"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
