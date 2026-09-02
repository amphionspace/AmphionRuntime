#!/usr/bin/env python3
"""
asr-service 并发压测脚本：测 RTF / latency / 错误率 / 吞吐 / 内存。

设计目标：
- 模拟 N 个并发客户端，每个客户端持续打 K 段 WAV → 服务端流式识别
- 测量：单流 RTF（端到端）、首包延迟、final 延迟、错误率
- 分位数：p50 / p90 / p99

依赖：
  pip install grpcio protobuf psutil

用法：
  # 1) 先生成 python proto stub（一次性）：
  python -m grpc_tools.protoc -I asr/server/proto \\
      --python_out=asr/server/bench \\
      --grpc_python_out=asr/server/bench \\
      asr/server/proto/asr.proto

  # 2) 跑压测：
  python asr/server/bench/bench_concurrent.py \\
      --target=localhost:50051 \\
      --wav-dir=shared/regression-set/short \\
      --concurrency=16 \\
      --duration=60 \\
      --report=/tmp/bench-report.json

退出码：
  0 全部完成
  1 部分客户端失败
  2 参数错误
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue
from typing import List, Optional

# 由 protoc 生成；运行前请先按 README 步骤生成 stub
try:
    import grpc  # type: ignore
    import asr_pb2 as pb  # type: ignore
    import asr_pb2_grpc as pb_grpc  # type: ignore
except ImportError as e:
    print(f"[ERROR] 依赖缺失：{e}\n请先 pip install grpcio protobuf 并按 README 生成 asr_pb2*.py", file=sys.stderr)
    sys.exit(2)


@dataclass
class WorkerStats:
    sessions: int = 0
    failures: int = 0
    first_partial_ms: List[float] = field(default_factory=list)
    final_ms: List[float] = field(default_factory=list)
    rtf: List[float] = field(default_factory=list)
    audio_seconds: float = 0.0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, description=__doc__)
    p.add_argument("--target", default="localhost:50051")
    p.add_argument("--wav-dir", required=True, type=Path)
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--duration", type=float, default=60.0, help="压测总时长（秒）")
    p.add_argument("--chunk-ms", type=int, default=100, help="每帧时长 ms")
    p.add_argument("--report", type=Path, default=Path("/tmp/bench-report.json"))
    return p.parse_args()


def load_wavs(wav_dir: Path) -> List[Path]:
    wavs = sorted(wav_dir.rglob("*.wav"))
    if not wavs:
        raise SystemExit(f"no wav under {wav_dir}")
    return wavs


def read_wav_int16(path: Path) -> tuple[int, bytes, float]:
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 1: raise SystemExit(f"{path}: not mono")
        if w.getsampwidth() != 2: raise SystemExit(f"{path}: not 16-bit")
        sr = w.getframerate()
        nframes = w.getnframes()
        raw = w.readframes(nframes)
    return sr, raw, nframes / sr


def worker_loop(worker_id: int, args, wavs: List[Path], deadline: float,
                stats_q: Queue):
    stats = WorkerStats()
    try:
        channel = grpc.insecure_channel(args.target,
                                        options=[("grpc.max_send_message_length", 8 * 1024 * 1024),
                                                  ("grpc.max_receive_message_length", 8 * 1024 * 1024)])
        stub = pb_grpc.AsrServiceStub(channel)
        wav_idx = 0

        while time.time() < deadline:
            wav = wavs[wav_idx % len(wavs)]
            wav_idx += 1
            sr, raw, dur_sec = read_wav_int16(wav)
            stats.audio_seconds += dur_sec

            chunk_bytes = int(sr * args.chunk_ms / 1000) * 2  # 16-bit
            t_start = time.time()

            def gen():
                cfg = pb.PcmRequest(session_config=pb.SessionConfig(
                    trace_id=f"bench-{worker_id}-{wav_idx}",
                    client_app="bench-py",
                    audio_format=pb.AudioFormat(sample_rate=sr, encoding=pb.PCM_S16LE, channels=1),
                    decoding=pb.Decoding(method=pb.GREEDY_SEARCH),
                    enable_endpoint=True,
                    include_token_timestamps=False,
                ))
                yield cfg
                # 按真实音频时长 pacing：每 chunk_ms 发一帧（模拟实时）
                i = 0
                while i < len(raw):
                    yield pb.PcmRequest(audio_chunk=pb.AudioChunk(data=raw[i:i + chunk_bytes]))
                    i += chunk_bytes
                    time.sleep(args.chunk_ms / 1000.0)
                yield pb.PcmRequest(end_of_stream=pb.EndOfStream())

            try:
                first_partial_t = None
                final_t = None
                for ev in stub.Recognize(gen(), timeout=120):
                    if ev.HasField("partial") and first_partial_t is None:
                        first_partial_t = time.time()
                    if ev.HasField("final"):
                        final_t = time.time()
                    if ev.HasField("error"):
                        stats.failures += 1
                        break
                stats.sessions += 1
                if first_partial_t:
                    stats.first_partial_ms.append((first_partial_t - t_start) * 1000)
                if final_t:
                    stats.final_ms.append((final_t - t_start) * 1000)
                    decode = final_t - t_start
                    if dur_sec > 0:
                        stats.rtf.append(decode / dur_sec)
            except grpc.RpcError as e:
                stats.failures += 1
                print(f"[w{worker_id}] grpc error: {e.code()} {e.details()}", file=sys.stderr)

    finally:
        stats_q.put((worker_id, stats))


def percentile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * q
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c: return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def aggregate(stats_list: List[WorkerStats]) -> dict:
    all_partial = []
    all_final = []
    all_rtf = []
    sessions = failures = 0
    audio_sec = 0.0
    for s in stats_list:
        all_partial.extend(s.first_partial_ms)
        all_final.extend(s.final_ms)
        all_rtf.extend(s.rtf)
        sessions += s.sessions
        failures += s.failures
        audio_sec += s.audio_seconds
    def pct(vs):
        return {
            "p50": percentile(vs, 0.5),
            "p90": percentile(vs, 0.9),
            "p95": percentile(vs, 0.95),
            "p99": percentile(vs, 0.99),
            "max": max(vs) if vs else 0.0,
            "mean": statistics.fmean(vs) if vs else 0.0,
            "count": len(vs),
        }
    return {
        "sessions": sessions,
        "failures": failures,
        "audio_seconds": audio_sec,
        "first_partial_ms": pct(all_partial),
        "final_ms": pct(all_final),
        "rtf": pct(all_rtf),
    }


def main() -> int:
    args = parse_args()
    wavs = load_wavs(args.wav_dir)
    print(f"[INFO] loaded {len(wavs)} wav from {args.wav_dir}")

    deadline = time.time() + args.duration
    stats_q: Queue = Queue()
    threads: List[threading.Thread] = []
    for i in range(args.concurrency):
        t = threading.Thread(target=worker_loop, args=(i, args, wavs, deadline, stats_q), daemon=True)
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    stats_list: List[WorkerStats] = []
    while not stats_q.empty():
        _, s = stats_q.get()
        stats_list.append(s)

    report = aggregate(stats_list)
    report["concurrency"] = args.concurrency
    report["duration_sec"] = args.duration
    report["target"] = args.target

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"[INFO] report -> {args.report}")
    return 0 if report["failures"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
