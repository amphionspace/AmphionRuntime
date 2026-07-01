#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import hashlib
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ws_client import transcribe_file  # noqa: E402


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def summarize(values: list[float]) -> str:
    if not values:
        return "n/a"
    values = sorted(values)
    p95_idx = min(len(values) - 1, int(len(values) * 0.95))
    return (
        f"min={min(values):.3f}, p50={statistics.median(values):.3f}, "
        f"p95={values[p95_idx]:.3f}, max={max(values):.3f}"
    )


def render_report(payload: dict) -> str:
    rows = []
    for item in payload["results"]:
        rows.append(
            "| {name} | {duration:.3f} | {elapsed:.3f} | {rtf:.3f} | {first} | {text} |".format(
                name=Path(item["file"]).name,
                duration=item["duration_sec"],
                elapsed=item["elapsed_sec"],
                rtf=item["rtf"],
                first=(
                    f"{item['first_partial_sec']:.3f}"
                    if item["first_partial_sec"] is not None
                    else "n/a"
                ),
                text=(item["final_text"] or "").replace("|", "｜"),
            )
        )

    return "\n".join(
        [
            "# ASR WebSocket Mac CPU 测试报告",
            "",
            "## 测试范围",
            "",
            f"- 测试时间：{payload['generated_at']}",
            f"- 服务地址：{payload['uri']}",
            f"- 音频目录：{payload['audio_dir']}",
            f"- 文件数量：{payload['file_count']}",
            f"- 并发数：{payload['concurrency']}",
            f"- 是否按实时速度发送：{payload['realtime']}",
            f"- chunk 大小：{payload['chunk_ms']} ms",
            f"- 模型：{payload['model_id']} / {payload['model_version']}",
            f"- provider：{payload['provider']}",
            "",
            "说明：本报告用于验证 Mac/CPU 阶段的服务功能、流式协议和调度逻辑。Mac CPU 测试不能代表 H20/CUDA 50 路容量，GPU 容量需在 H20 上单独压测。",
            "",
            "## 汇总",
            "",
            f"- 音频总时长：{payload['duration_sec_total']:.3f} s",
            f"- 单文件耗时分布：{payload['elapsed_summary']}",
            f"- 单文件 RTF 分布：{payload['rtf_summary']}",
            f"- 首个 partial 延迟分布：{payload['first_partial_summary']}",
            "",
            "## 样本明细",
            "",
            "| 文件 | 音频时长(s) | 端到端耗时(s) | RTF | 首个 partial(s) | final 文本 |",
            "| --- | ---: | ---: | ---: | ---: | --- |",
            *rows,
            "",
            "## 音频 SHA-256",
            "",
            "| 文件 | SHA-256 |",
            "| --- | --- |",
            *[
                f"| {Path(item['file']).name} | {item['sha256']} |"
                for item in payload["results"]
            ],
            "",
            "## 已知边界",
            "",
            "- 这批音频包含多人重叠、交通背景噪声和声纹注册片段；当前服务是单流 ASR，不做说话人分离或声纹跟踪。",
            "- 缺少人工标注真值，因此本报告不计算 WER/CER，只记录服务输出文本与性能指标。",
        ]
    )


async def amain(args: argparse.Namespace) -> None:
    audio_dir = Path(args.audio_dir).resolve()
    wavs = sorted(audio_dir.glob("*.wav"))
    if not wavs:
        raise SystemExit(f"no wav files found in {audio_dir}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(args.concurrency)

    async def run_one(path: Path) -> dict:
        async with sem:
            result = await transcribe_file(
                args.uri,
                path,
                chunk_ms=args.chunk_ms,
                realtime=args.realtime,
            )
            result["sha256"] = sha256(path)
            result["event_count"] = len(result["events"])
            return result

    results = await asyncio.gather(*(run_one(path) for path in wavs))
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "uri": args.uri,
        "audio_dir": str(audio_dir),
        "file_count": len(results),
        "concurrency": args.concurrency,
        "realtime": args.realtime,
        "chunk_ms": args.chunk_ms,
        "model_id": args.model_id,
        "model_version": args.model_version,
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
    parser = argparse.ArgumentParser(description="Run ASR WS test suite and write Markdown report")
    parser.add_argument("audio_dir")
    parser.add_argument("--uri", default="ws://127.0.0.1:8010")
    parser.add_argument("--output-dir", default="asr/ws-server/reports/latest")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--chunk-ms", type=int, default=100)
    parser.add_argument("--realtime", action="store_true")
    parser.add_argument("--model-id", default="unknown")
    parser.add_argument("--model-version", default="unknown")
    parser.add_argument("--provider", default="cpu")
    asyncio.run(amain(parser.parse_args()))


if __name__ == "__main__":
    main()
