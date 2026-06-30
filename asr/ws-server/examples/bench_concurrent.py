#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ws_client import transcribe_file  # noqa: E402


def summarize(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "p50": None, "p95": None, "max": None}
    sorted_values = sorted(values)
    p95_idx = min(len(sorted_values) - 1, int(len(sorted_values) * 0.95))
    return {
        "min": min(values),
        "p50": statistics.median(values),
        "p95": sorted_values[p95_idx],
        "max": max(values),
    }


async def amain(args: argparse.Namespace) -> None:
    wavs = sorted(Path(args.audio_dir).glob("*.wav"))
    if args.limit:
        wavs = wavs[: args.limit]
    if not wavs:
        raise SystemExit(f"no wav files found in {args.audio_dir}")

    sem = asyncio.Semaphore(args.concurrency)

    async def run_one(path: Path) -> dict:
        async with sem:
            return await transcribe_file(
                args.uri,
                path,
                chunk_ms=args.chunk_ms,
                realtime=args.realtime,
            )

    results = await asyncio.gather(*(run_one(path) for path in wavs))
    summary = {
        "uri": args.uri,
        "audio_dir": str(Path(args.audio_dir).resolve()),
        "file_count": len(results),
        "concurrency": args.concurrency,
        "realtime": args.realtime,
        "duration_sec_total": sum(r["duration_sec"] for r in results),
        "elapsed_sec": summarize([r["elapsed_sec"] for r in results]),
        "rtf": summarize([r["rtf"] for r in results]),
        "first_partial_sec": summarize(
            [r["first_partial_sec"] for r in results if r["first_partial_sec"] is not None]
        ),
        "results": results,
    }
    if args.output:
        Path(args.output).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Concurrent ASR WebSocket benchmark")
    parser.add_argument("audio_dir", help="Directory containing WAV files")
    parser.add_argument("--uri", default="ws://127.0.0.1:8010")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--chunk-ms", type=int, default=100)
    parser.add_argument("--realtime", action="store_true")
    parser.add_argument("--output", help="Optional JSON output path")
    asyncio.run(amain(parser.parse_args()))


if __name__ == "__main__":
    main()
