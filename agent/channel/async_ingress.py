"""可关闭的异步入口。默认不启用，评测不经过这里。"""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Any, Callable

OVERFLOW_MESSAGE = "现在排队的人有点多，稍后再叫我～"
_BROKEN = False
_LOOP: asyncio.AbstractEventLoop | None = None
_INGRESS: AsyncIngress | None = None
_THREAD: threading.Thread | None = None


def ingress_enabled() -> bool:
    return os.environ.get("QQ_ASYNC_INGRESS") == "1"


class AsyncIngress:
    """有界总队列。每个会话一条顺序车道，不同会话可以并行。"""

    def __init__(
        self,
        handler: Callable[[dict[str, Any]], None],
        *,
        capacity: int = 8,
        concurrency: int = 2,
    ) -> None:
        self.handler = handler
        self.capacity = capacity
        self.concurrency = concurrency
        self.completed: list[str] = []
        self.max_inflight = 0
        self._inflight = 0
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=capacity)
        self._lanes: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._sem: asyncio.Semaphore | None = None
        self._lock: asyncio.Lock | None = None
        self.sealed: set[str] = set()

    def submit(self, event: dict[str, Any]) -> bool:
        if self._queue.full():
            return False
        self._queue.put_nowait(event)
        return True

    async def drain(self) -> None:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            await self._drain_locked()

    async def _drain_locked(self) -> None:
        self._sem = asyncio.Semaphore(max(1, self.concurrency))
        while not self._queue.empty():
            event = self._queue.get_nowait()
            key = str(event["session"])
            self._lanes.setdefault(key, asyncio.Queue()).put_nowait(event)
        workers = [asyncio.create_task(self._lane(key)) for key in self._lanes]
        if workers:
            await asyncio.gather(*workers)

    async def _lane(self, key: str) -> None:
        lane = self._lanes[key]
        while not lane.empty():
            event = await lane.get()
            effect = str(event.get("effect_id") or "")
            if effect and effect in self.sealed:
                continue
            assert self._sem is not None
            async with self._sem:
                self._inflight += 1
                self.max_inflight = max(self.max_inflight, self._inflight)
                try:
                    await asyncio.to_thread(self.handler, event)
                except Exception:
                    if effect:
                        self.sealed.add(effect)
                else:
                    if event.get("irreversible") and effect:
                        self.sealed.add(effect)
                finally:
                    self._inflight -= 1
                    self.completed.append(str(event.get("mark") or key))


def offer(event: dict[str, Any], handler: Callable[[dict[str, Any]], None]) -> bool | None:
    """启用失败时返回 None，调用方继续走原来的同步入口。队列满返回 False。"""
    global _BROKEN, _LOOP, _INGRESS, _THREAD
    if _BROKEN:
        return None
    try:
        if _LOOP is None or _INGRESS is None:
            _INGRESS = AsyncIngress(handler, capacity=8, concurrency=3)
            _LOOP = asyncio.new_event_loop()

            def _spin() -> None:
                assert _LOOP is not None
                asyncio.set_event_loop(_LOOP)
                _LOOP.run_forever()

            _THREAD = threading.Thread(target=_spin, name="qq-async-ingress", daemon=True)
            _THREAD.start()
        assert _LOOP is not None and _INGRESS is not None
        future = asyncio.run_coroutine_threadsafe(_submit(_INGRESS, event), _LOOP)
        return bool(future.result(timeout=2))
    except Exception:
        _BROKEN = True
        return None


async def _submit(ingress: AsyncIngress, event: dict[str, Any]) -> bool:
    accepted = ingress.submit(event)
    if accepted:
        asyncio.create_task(ingress.drain())
    return accepted
