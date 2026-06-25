from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import numpy as np

from . import metrics
from .manifest import Manifest
from .protocol import (
    ERR_AUDIO_FORMAT_MISMATCH,
    ERR_DECODE_FAILED,
    ERR_INVALID_ARGUMENT,
    error_event,
    event,
    final_event,
    parse_json_frame,
    parse_start,
    partial_event,
)
from .recognizer import result_to_dict
from .scheduler import DecodeScheduler

LOG = logging.getLogger(__name__)


class StreamingSession:
    def __init__(
        self,
        connection: Any,
        *,
        recognizer: Any,
        manifest: Manifest,
        scheduler: DecodeScheduler,
        session_idle_timeout_sec: float,
    ) -> None:
        self.connection = connection
        self.recognizer = recognizer
        self.manifest = manifest
        self.scheduler = scheduler
        self.session_idle_timeout_sec = session_idle_timeout_sec
        self.stream: Any | None = None
        self.trace_id = ""
        self.include_token_timestamps = False
        self.enable_endpoint = True
        self.last_partial = ""
        self.last_audio_time = time.monotonic()

    async def run(self) -> None:
        metrics.ACTIVE_SESSIONS.inc()
        try:
            await self._run()
        except asyncio.TimeoutError:
            await self._send_error(ERR_DECODE_FAILED, "session idle timeout")
        except Exception as exc:  # noqa: BLE001 - send protocol error before closing
            LOG.exception("session failed")
            await self._send_error(ERR_DECODE_FAILED, str(exc))
        finally:
            metrics.ACTIVE_SESSIONS.dec()

    async def _run(self) -> None:
        first = await asyncio.wait_for(self.connection.recv(), timeout=self.session_idle_timeout_sec)
        if not isinstance(first, str):
            await self._send_error(ERR_INVALID_ARGUMENT, "first frame must be JSON start")
            return
        data = parse_json_frame(first)
        if data.get("type") != "start":
            await self._send_error(ERR_INVALID_ARGUMENT, "first JSON frame must have type=start")
            return

        start = parse_start(data)
        self.trace_id = start.trace_id
        self.include_token_timestamps = start.include_token_timestamps
        self.enable_endpoint = start.enable_endpoint
        if start.audio_format.sample_rate != self.manifest.sample_rate or start.audio_format.channels != 1:
            await self._send_error(ERR_AUDIO_FORMAT_MISMATCH, "audio_format mismatch with model manifest")
            return
        if start.audio_format.encoding not in {"pcm_s16le", "pcm_f32le"}:
            await self._send_error(ERR_INVALID_ARGUMENT, "unsupported audio encoding")
            return

        self.stream = self.recognizer.create_stream(start.hotwords or None)
        await self.connection.send(event("session_started"))

        while True:
            message = await asyncio.wait_for(self.connection.recv(), timeout=self.session_idle_timeout_sec)
            if isinstance(message, bytes):
                await self._handle_audio(message, start.audio_format.encoding, start.audio_format.sample_rate)
                continue

            data = parse_json_frame(message)
            msg_type = data.get("type")
            if msg_type == "stop":
                await self._finish()
                return
            if msg_type == "update_hotwords":
                self.stream = self.recognizer.create_stream(str(data.get("hotwords", "")) or None)
                self.last_partial = ""
                await self.connection.send(event("hotwords_updated"))
                continue
            await self._send_error(ERR_INVALID_ARGUMENT, f"unsupported JSON frame type: {msg_type}")

    async def _handle_audio(self, raw: bytes, encoding: str, sample_rate: int) -> None:
        if self.stream is None:
            await self._send_error(ERR_INVALID_ARGUMENT, "audio received before start")
            return
        samples = _decode_pcm(raw, encoding)
        if samples.size == 0:
            return

        self.last_audio_time = time.monotonic()
        audio_ms = float(samples.size) * 1000.0 / sample_rate
        t0 = time.perf_counter()
        self.stream.accept_waveform(sample_rate, samples)
        while self.recognizer.is_ready(self.stream):
            await self.scheduler.compute_and_decode(self.stream)
        decode_ms = (time.perf_counter() - t0) * 1000.0
        metrics.DECODE_LATENCY_MS.observe(decode_ms)
        metrics.QUEUE_DEPTH.set(self.scheduler.queue_depth())

        if self.enable_endpoint and self.recognizer.is_endpoint(self.stream):
            result = result_to_dict(self.recognizer.get_result(self.stream))
            await self.connection.send(event("endpoint"))
            await self._send_final(result)
            self.recognizer.reset(self.stream)
            self.last_partial = ""
            return

        result = result_to_dict(self.recognizer.get_result(self.stream))
        text = result.get("text", "")
        if text and text != self.last_partial:
            self.last_partial = text
            await self.connection.send(partial_event(result, self.include_token_timestamps))
            metrics.PARTIAL_TOTAL.labels(self.manifest.model_id).inc()

    async def _finish(self) -> None:
        if self.stream is None:
            await self.connection.send(event("session_ended", trace_id=self.trace_id))
            return
        self.stream.input_finished()
        while self.recognizer.is_ready(self.stream):
            await self.scheduler.compute_and_decode(self.stream)
        result = result_to_dict(self.recognizer.get_result(self.stream))
        if result.get("text"):
            await self._send_final(result)
        await self.connection.send(event("session_ended", trace_id=self.trace_id))

    async def _send_final(self, result: dict[str, Any]) -> None:
        await self.connection.send(final_event(result, self.include_token_timestamps))
        metrics.FINAL_TOTAL.labels(self.manifest.model_id).inc()

    async def _send_error(self, code: int, message: str) -> None:
        metrics.ERROR_TOTAL.labels(self.manifest.model_id, str(code)).inc()
        try:
            await self.connection.send(error_event(code, message))
        except Exception:  # noqa: BLE001
            LOG.debug("failed to send error event", exc_info=True)


def _decode_pcm(raw: bytes, encoding: str) -> np.ndarray:
    if encoding == "pcm_s16le":
        return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if encoding == "pcm_f32le":
        return np.frombuffer(raw, dtype="<f4").astype(np.float32)
    return np.asarray([], dtype=np.float32)
