#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import time
import wave

from websockets.asyncio.client import connect


def read_wav_s16le(path: Path) -> tuple[int, bytes, float]:
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        if channels != 1 or sample_width != 2:
            raise ValueError(f"{path} must be 16-bit mono PCM WAV")
        raw = wf.readframes(wf.getnframes())
        duration = wf.getnframes() / sample_rate
        return sample_rate, raw, duration


async def transcribe_file(
    uri: str,
    wav_path: Path,
    *,
    chunk_ms: int,
    realtime: bool,
    include_token_timestamps: bool = False,
) -> dict:
    sample_rate, raw, duration = read_wav_s16le(wav_path)
    bytes_per_chunk = int(sample_rate * chunk_ms / 1000) * 2
    started = time.perf_counter()
    first_partial_sec: float | None = None
    events: list[dict] = []
    final_texts: list[str] = []

    async with connect(uri, max_size=None) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "start",
                    "trace_id": wav_path.stem,
                    "client_app": "amphion-asr-ws-client",
                    "audio_format": {
                        "sample_rate": sample_rate,
                        "encoding": "pcm_s16le",
                        "channels": 1,
                    },
                    "include_token_timestamps": include_token_timestamps,
                },
                ensure_ascii=False,
            )
        )

        async def receiver() -> None:
            nonlocal first_partial_sec
            async for message in ws:
                data = json.loads(message)
                data["client_recv_sec"] = time.perf_counter() - started
                events.append(data)
                if data.get("type") == "partial" and first_partial_sec is None:
                    first_partial_sec = data["client_recv_sec"]
                if data.get("type") == "final":
                    final_texts.append(data.get("text", ""))
                if data.get("type") in {"session_ended", "error"}:
                    break

        recv_task = asyncio.create_task(receiver())
        for offset in range(0, len(raw), bytes_per_chunk):
            await ws.send(raw[offset : offset + bytes_per_chunk])
            if realtime:
                await asyncio.sleep(chunk_ms / 1000)
        await ws.send(json.dumps({"type": "stop"}))
        await recv_task

    elapsed = time.perf_counter() - started
    return {
        "file": str(wav_path),
        "duration_sec": duration,
        "elapsed_sec": elapsed,
        "rtf": elapsed / duration if duration else 0.0,
        "first_partial_sec": first_partial_sec,
        "final_text": "".join(final_texts),
        "events": events,
    }


async def amain(args: argparse.Namespace) -> None:
    result = await transcribe_file(
        args.uri,
        Path(args.wav),
        chunk_ms=args.chunk_ms,
        realtime=args.realtime,
        include_token_timestamps=args.include_token_timestamps,
    )
    if args.output:
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "events"}, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Streaming ASR WebSocket file client")
    parser.add_argument("wav", help="16kHz mono s16le WAV file")
    parser.add_argument("--uri", default="ws://127.0.0.1:8010", help="ASR WebSocket URI")
    parser.add_argument("--chunk-ms", type=int, default=100, help="PCM chunk size")
    parser.add_argument("--realtime", action="store_true", help="Sleep between chunks to emulate realtime input")
    parser.add_argument("--include-token-timestamps", action="store_true")
    parser.add_argument("--output", help="Optional JSON output path")
    asyncio.run(amain(parser.parse_args()))


if __name__ == "__main__":
    main()
