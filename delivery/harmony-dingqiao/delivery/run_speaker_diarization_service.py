#!/usr/bin/env python3
"""Reference HTTP service for incremental speaker diarization windows.

The Harmony SDK uploads one PCM16 mono 16 kHz window at a time.  This service
keeps the model hot, performs pyannote segmentation and ERes2Net embedding
extraction, and returns only window-local evidence.  Stable speaker numbering
and final whole-session clustering remain in the SDK.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import sherpa_onnx


SAMPLE_RATE = 16_000
WINDOW_SAMPLES = 160_000
MAX_EMBEDDING_SAMPLES = int(2.5 * SAMPLE_RATE)
MIN_EMBEDDING_SAMPLES = SAMPLE_RATE
PROTOCOL_VERSION = "1"
WINDOW_PATH = "/v1/speaker-diarization/window"


@dataclass(frozen=True)
class WindowMetadata:
    job_id: str
    sample_count: int
    window_start_sample: int
    content_start_sample: int
    real_end_sample: int
    commit_start_sample: int
    stable_end_sample: int
    final_window: bool


@dataclass(frozen=True)
class AtomicSegment:
    start_sample: int
    end_sample: int
    speaker: int
    speaker_mask: int


def _required_int(headers: Any, name: str, minimum: int = 0) -> int:
    value = headers.get(name)
    if value is None:
        raise ValueError(f"missing header {name}")
    parsed = int(value)
    if parsed < minimum:
        raise ValueError(f"invalid header {name}")
    return parsed


def _metadata(headers: Any) -> WindowMetadata:
    if headers.get("X-Amphion-Protocol-Version") != PROTOCOL_VERSION:
        raise ValueError("unsupported protocol version")
    job_id = headers.get("X-Amphion-Job-Id", "")
    if not job_id or len(job_id) > 80:
        raise ValueError("invalid job id")
    sample_rate = _required_int(headers, "X-Amphion-Sample-Rate", 1)
    if sample_rate != SAMPLE_RATE:
        raise ValueError("sample rate must be 16000")
    sample_count = _required_int(headers, "X-Amphion-Sample-Count")
    content_start = _required_int(headers, "X-Amphion-Content-Start-Sample")
    if sample_count > WINDOW_SAMPLES or content_start + sample_count > WINDOW_SAMPLES:
        raise ValueError("window sample range is invalid")
    return WindowMetadata(
        job_id=job_id,
        sample_count=sample_count,
        window_start_sample=_required_int(headers, "X-Amphion-Window-Start-Sample"),
        content_start_sample=content_start,
        real_end_sample=_required_int(headers, "X-Amphion-Real-End-Sample"),
        commit_start_sample=_required_int(headers, "X-Amphion-Commit-Start-Sample"),
        stable_end_sample=_required_int(headers, "X-Amphion-Stable-End-Sample"),
        final_window=headers.get("X-Amphion-Final-Window", "false").lower() == "true",
    )


def _merge_atomic_segments(segments: Iterable[AtomicSegment]) -> list[AtomicSegment]:
    merged: list[AtomicSegment] = []
    for segment in segments:
        if segment.end_sample <= segment.start_sample:
            continue
        if (merged and merged[-1].end_sample == segment.start_sample
                and merged[-1].speaker == segment.speaker
                and merged[-1].speaker_mask == segment.speaker_mask):
            previous = merged[-1]
            merged[-1] = AtomicSegment(
                previous.start_sample,
                segment.end_sample,
                previous.speaker,
                previous.speaker_mask,
            )
        else:
            merged.append(segment)
    return merged


def _to_overlap_aware_segments(raw_segments: list[Any]) -> list[AtomicSegment]:
    if not raw_segments:
        return []
    raw_speakers = sorted({int(segment.speaker) for segment in raw_segments})
    local_speaker = {speaker: index for index, speaker in enumerate(raw_speakers[:3])}
    clipped: list[tuple[int, int, int]] = []
    boundaries: set[int] = set()
    for segment in raw_segments:
        speaker = local_speaker.get(int(segment.speaker))
        if speaker is None:
            continue
        start = max(0, min(WINDOW_SAMPLES, round(float(segment.start) * SAMPLE_RATE)))
        end = max(start, min(WINDOW_SAMPLES, round(float(segment.end) * SAMPLE_RATE)))
        if end <= start:
            continue
        clipped.append((start, end, speaker))
        boundaries.add(start)
        boundaries.add(end)
    ordered = sorted(boundaries)
    atomic: list[AtomicSegment] = []
    for index in range(len(ordered) - 1):
        start, end = ordered[index], ordered[index + 1]
        if end <= start:
            continue
        active = sorted({speaker for left, right, speaker in clipped
                         if left < end and right > start})
        if not active:
            continue
        mask = sum(1 << speaker for speaker in active)
        atomic.append(AtomicSegment(start, end, active[0], mask))
    return _merge_atomic_segments(atomic)


class DiarizationModels:
    def __init__(self, segmentation_model: Path, embedding_model: Path, num_threads: int):
        config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model=str(segmentation_model)
                ),
                num_threads=num_threads,
            ),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(embedding_model), num_threads=num_threads
            ),
            clustering=sherpa_onnx.FastClusteringConfig(
                num_clusters=-1, threshold=0.5
            ),
            min_duration_on=0.3,
            min_duration_off=0.5,
        )
        if not config.validate():
            raise ValueError("speaker diarization model configuration is invalid")
        self._diarization = sherpa_onnx.OfflineSpeakerDiarization(config)
        embedding_config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(embedding_model), num_threads=num_threads
        )
        if not embedding_config.validate():
            raise ValueError("speaker embedding model configuration is invalid")
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(embedding_config)
        self._lock = threading.Lock()

    def process(self, pcm16: bytes, metadata: WindowMetadata) -> dict[str, Any]:
        started = time.monotonic()
        input_samples = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
        samples = np.zeros(WINDOW_SAMPLES, dtype=np.float32)
        samples[metadata.content_start_sample:
                metadata.content_start_sample + metadata.sample_count] = input_samples
        with self._lock:
            raw = list(self._diarization.process(samples).sort_by_start_time())
            segments = _to_overlap_aware_segments(raw)
            embeddings = self._embeddings(samples, segments)
        inference_ms = round((time.monotonic() - started) * 1000)
        return {
            "protocolVersion": 1,
            "jobId": metadata.job_id,
            "windowStartSample": metadata.window_start_sample,
            "contentStartInWindowSample": metadata.content_start_sample,
            "realEndSample": metadata.real_end_sample,
            "commitStartSample": metadata.commit_start_sample,
            "stableEndSample": metadata.stable_end_sample,
            "finalWindow": metadata.final_window,
            "result": {
                "segments": [
                    {
                        "startSample": segment.start_sample,
                        "endSample": segment.end_sample,
                        "speaker": segment.speaker,
                        "speakerMask": segment.speaker_mask,
                    }
                    for segment in segments
                ],
                "embeddings": embeddings,
                "inferenceMs": inference_ms,
            },
        }

    def _embeddings(self, samples: np.ndarray,
                    segments: list[AtomicSegment]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for speaker in range(3):
            expected_mask = 1 << speaker
            chunks: list[np.ndarray] = []
            total = 0
            for segment in segments:
                if segment.speaker_mask != expected_mask or total >= MAX_EMBEDDING_SAMPLES:
                    continue
                take = min(segment.end_sample - segment.start_sample,
                           MAX_EMBEDDING_SAMPLES - total)
                if take <= 0:
                    continue
                chunks.append(samples[segment.start_sample:segment.start_sample + take])
                total += take
            if total < MIN_EMBEDDING_SAMPLES:
                continue
            speech = np.ascontiguousarray(np.concatenate(chunks))
            stream = self._extractor.create_stream()
            stream.accept_waveform(sample_rate=SAMPLE_RATE, waveform=speech)
            stream.input_finished()
            if not self._extractor.is_ready(stream):
                continue
            embedding = np.asarray(self._extractor.compute(stream), dtype=np.float32)
            output.append({
                "localSpeaker": speaker,
                "speechSamples": total,
                "embedding": embedding.tolist(),
            })
        return output


class DiarizationRequestHandler(BaseHTTPRequestHandler):
    server: "DiarizationHttpServer"

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self._json_error(HTTPStatus.NOT_FOUND, "not found")
            return
        self._json(HTTPStatus.OK, {"status": "ok", "protocolVersion": 1})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != WINDOW_PATH:
            self._json_error(HTTPStatus.NOT_FOUND, "not found")
            return
        if self.server.bearer_token:
            expected = f"Bearer {self.server.bearer_token}"
            if self.headers.get("Authorization") != expected:
                self._json_error(HTTPStatus.UNAUTHORIZED, "authentication failed")
                return
        try:
            metadata = _metadata(self.headers)
            content_length = _required_int(self.headers, "Content-Length")
            expected_length = metadata.sample_count * 2
            if content_length != expected_length or content_length > WINDOW_SAMPLES * 2:
                raise ValueError("PCM body length does not match sample count")
            pcm16 = self.rfile.read(content_length)
            if len(pcm16) != content_length:
                raise ValueError("incomplete PCM body")
            response = self.server.models.process(pcm16, metadata)
        except ValueError as error:
            self._json_error(HTTPStatus.BAD_REQUEST, str(error))
            return
        except Exception as error:  # keep one failed window isolated from the service process
            self._json_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"inference failed: {error}")
            return
        self._json(HTTPStatus.OK, response)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} {fmt % args}", flush=True)

    def _json_error(self, status: HTTPStatus, message: str) -> None:
        self._json(status, {"error": message})

    def _json(self, status: HTTPStatus, value: dict[str, Any]) -> None:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class DiarizationHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], models: DiarizationModels,
                 bearer_token: str):
        super().__init__(address, DiarizationRequestHandler)
        self.models = models
        self.bearer_token = bearer_token


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--segmentation-model", type=Path, required=True)
    parser.add_argument("--embedding-model", type=Path, required=True)
    parser.add_argument("--num-threads", type=int, default=2)
    parser.add_argument("--bearer-token", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.segmentation_model.is_file() or not args.embedding_model.is_file():
        raise SystemExit("model file is missing")
    models = DiarizationModels(
        args.segmentation_model, args.embedding_model, max(1, args.num_threads)
    )
    server = DiarizationHttpServer((args.host, args.port), models, args.bearer_token)
    print(
        json.dumps({
            "status": "ready",
            "url": f"http://{args.host}:{args.port}{WINDOW_PATH}",
            "protocolVersion": 1,
        }, separators=(",", ":")),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
