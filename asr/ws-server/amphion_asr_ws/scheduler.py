from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import logging
import time
from typing import Any

LOG = logging.getLogger(__name__)


@dataclass
class SchedulerStats:
    decoded_batches: int = 0
    decoded_streams: int = 0
    max_observed_batch: int = 0
    last_decode_ms: float = 0.0


class DecodeScheduler:
    """Central batch scheduler shared by CPU and CUDA providers."""

    def __init__(
        self,
        recognizer: Any,
        *,
        max_wait_ms: float,
        max_batch_size: int,
        nn_pool_size: int,
    ) -> None:
        self.recognizer = recognizer
        self.max_wait_ms = max_wait_ms
        self.max_batch_size = max_batch_size
        self.nn_pool = ThreadPoolExecutor(max_workers=nn_pool_size, thread_name_prefix="asr-nn")
        self.queue: asyncio.Queue[tuple[Any, asyncio.Future[None]]] = asyncio.Queue()
        self.stats = SchedulerStats()
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._consume(), name="asr-decode-scheduler")

    async def close(self) -> None:
        self._closed = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.nn_pool.shutdown(wait=True, cancel_futures=True)

    def queue_depth(self) -> int:
        return self.queue.qsize()

    async def compute_and_decode(self, stream: Any) -> None:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        await self.queue.put((stream, future))
        await future

    async def _consume(self) -> None:
        while not self._closed:
            if self.queue.empty():
                await asyncio.sleep(self.max_wait_ms / 1000.0)
                continue

            batch: list[tuple[Any, asyncio.Future[None]]] = []
            try:
                while len(batch) < self.max_batch_size:
                    item = self.queue.get_nowait()
                    if not item[1].cancelled():
                        batch.append(item)
            except asyncio.QueueEmpty:
                pass

            if not batch:
                continue

            stream_list = [item[0] for item in batch]
            future_list = [item[1] for item in batch]
            loop = asyncio.get_running_loop()
            start = time.perf_counter()
            try:
                await loop.run_in_executor(self.nn_pool, self.recognizer.decode_streams, stream_list)
            except Exception as exc:  # noqa: BLE001 - propagate to all waiting sessions
                LOG.exception("decode_streams failed")
                for future in future_list:
                    if not future.done():
                        future.set_exception(exc)
            else:
                decode_ms = (time.perf_counter() - start) * 1000.0
                self.stats.decoded_batches += 1
                self.stats.decoded_streams += len(stream_list)
                self.stats.max_observed_batch = max(self.stats.max_observed_batch, len(stream_list))
                self.stats.last_decode_ms = decode_ms
                for future in future_list:
                    if not future.done():
                        future.set_result(None)
            finally:
                for _ in batch:
                    self.queue.task_done()
