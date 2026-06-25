#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

from websockets.asyncio.server import ServerConnection, serve

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from amphion_asr_ws.manifest import load_manifest  # noqa: E402
from amphion_asr_ws.recognizer import build_recognizer  # noqa: E402
from amphion_asr_ws.scheduler import DecodeScheduler  # noqa: E402
from amphion_asr_ws.session import StreamingSession  # noqa: E402
from run_audio_suite import render_report, sha256, summarize  # noqa: E402
from ws_client import transcribe_file  # noqa: E402


async def amain(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.manifest, prefer_fp32=args.provider == "cuda")
    recognizer = build_recognizer(
        manifest,
        provider=args.provider,
        num_threads=args.num_threads,
        debug=args.debug,
    )
    scheduler = DecodeScheduler(
        recognizer,
        max_wait_ms=args.max_wait_ms,
        max_batch_size=args.max_batch_size,
        nn_pool_size=args.nn_pool_size,
    )
    scheduler.start()

    sem = asyncio.Semaphore(args.max_active_connections)

    async def handler(connection: ServerConnection) -> None:
        async with sem:
            session = StreamingSession(
                connection,
                recognizer=recognizer,
                manifest=manifest,
                scheduler=scheduler,
                session_idle_timeout_sec=args.session_idle_timeout_sec,
            )
            await session.run()

    audio_dir = Path(args.audio_dir).resolve()
    wavs = sorted(audio_dir.glob("*.wav"))
    if not wavs:
        raise SystemExit(f"no wav files found in {audio_dir}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    uri = f"ws://127.0.0.1:{args.port}"
    async with serve(handler, "127.0.0.1", args.port, max_size=None):
        client_sem = asyncio.Semaphore(args.concurrency)

        async def run_one(path: Path) -> dict:
            async with client_sem:
                result = await transcribe_file(
                    uri,
                    path,
                    chunk_ms=args.chunk_ms,
                    realtime=args.realtime,
                )
                result["sha256"] = sha256(path)
                result["event_count"] = len(result["events"])
                return result

        results = await asyncio.gather(*(run_one(path) for path in wavs))

    await scheduler.close()

    payload = {
        "generated_at": args.generated_at,
        "uri": uri,
        "audio_dir": str(audio_dir),
        "file_count": len(results),
        "concurrency": args.concurrency,
        "realtime": args.realtime,
        "chunk_ms": args.chunk_ms,
        "model_id": manifest.model_id,
        "model_version": manifest.version,
        "provider": args.provider,
        "duration_sec_total": sum(r["duration_sec"] for r in results),
        "elapsed_summary": summarize([r["elapsed_sec"] for r in results]),
        "rtf_summary": summarize([r["rtf"] for r in results]),
        "first_partial_summary": summarize(
            [r["first_partial_sec"] for r in results if r["first_partial_sec"] is not None]
        ),
        "results": results,
    }
    json_path = out_dir / "asr_ws_audio_suite_results.json"
    md_path = out_dir / "asr_ws_audio_suite_report.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_report(payload), encoding="utf-8")
    print(f"json={json_path}")
    print(f"report={md_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Start managed ASR WS server and run audio test suite")
    parser.add_argument("audio_dir")
    parser.add_argument("--manifest", default=str(REPO_ROOT / "asr/ws-server/deploy/manifest.local.cpu.json"))
    parser.add_argument("--provider", default="cpu")
    parser.add_argument("--num-threads", type=int, default=4)
    parser.add_argument("--max-batch-size", type=int, default=8)
    parser.add_argument("--max-wait-ms", type=float, default=10.0)
    parser.add_argument("--nn-pool-size", type=int, default=1)
    parser.add_argument("--max-active-connections", type=int, default=100)
    parser.add_argument("--session-idle-timeout-sec", type=float, default=300.0)
    parser.add_argument("--port", type=int, default=18110)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--chunk-ms", type=int, default=100)
    parser.add_argument("--realtime", action="store_true")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "asr/ws-server/reports/latest"))
    parser.add_argument("--generated-at", default="2026-06-25T19:00:00")
    parser.add_argument("--debug", action="store_true")
    asyncio.run(amain(parser.parse_args()))


if __name__ == "__main__":
    main()
