#!/usr/bin/env python3
"""Generate a focused 200-case edge text payload suite.

This suite is intentionally short and text-focused. It does not replace the
runtime stability 100/424/1000 suites; it provides compact payloads for numbers,
mixed Chinese/English, complex symbols, emoji, and random-looking text.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "tts" / "android" / "testdata" / "dingqiao_batch_cases"
JSONL_PATH = OUT_DIR / "android_v3_sdk_edge_text_200_cases.jsonl"
SUMMARY_PATH = OUT_DIR / "android_v3_sdk_edge_text_200_summary.json"

CASE_VERSION = "dingqiao-edge-text-200-v1"
MAX_TEXT_CHARS = 500
TOTAL_CASES = 200

EDGE_COUNTS = {
    "numeric-heavy": 32,
    "zh-en-mixed": 32,
    "complex-symbols": 28,
    "emoji-mixed": 28,
    "random-text": 28,
    "code-id-url-path": 28,
    "punctuation-whitespace": 24,
}

BASE_PARAMS: dict[str, Any] = {
    "language": "zh-en",
    "voiceId": "lits-female-02",
    "languageContext": "zh-CN",
    "playType": "SYNTHESIZE_ONLY",
    "queueMode": "PREEMPT",
    "speed": 1.0,
    "pitch": 1.0,
    "volume": 1.0,
    "audioType": "pcm",
    "chunkSize": 50,
    "pcmQueueCapacity": 32,
    "timeoutMs": 90_000,
}

METRICS = [
    "startLatencyMs",
    "firstPacketMs",
    "synthesisMs",
    "audioDurationMs",
    "rtf",
    "bytes",
    "chunkCount",
    "callbackCount",
    "terminalCallbackCount",
    "javaHeap",
    "nativeHeap",
    "rss",
    "fdCount",
    "threadCount",
    "tnChildProcessCount",
    "stderrWatcherThreadCount",
]

ASSERTIONS = [
    "no_crash",
    "no_unexpected_error",
    "complete_callback",
    "terminal_state_observed",
]


def profile(i: int) -> dict[str, Any]:
    profiles = [
        {"speed": 1.0, "pitch": 1.0, "volume": 1.0, "chunkSize": 50, "pcmQueueCapacity": 32},
        {"speed": 0.85, "pitch": 0.9, "volume": 0.9, "chunkSize": 32, "pcmQueueCapacity": 8},
        {"speed": 1.15, "pitch": 1.1, "volume": 1.1, "chunkSize": 64, "pcmQueueCapacity": 16},
        {"speed": 1.35, "pitch": 1.0, "volume": 0.75, "chunkSize": 100, "pcmQueueCapacity": 4},
    ]
    return profiles[i % len(profiles)]


def operation_for(edge_type: str, local_index: int) -> str:
    if local_index % 17 == 0:
        return "streaming-buffer-cycle"
    if local_index % 19 == 0:
        return "synthesize-and-play-route"
    if edge_type == "numeric-heavy" and local_index % 7 == 0:
        return "parameter-boundary-speak"
    return "speak"


def text_numeric(i: int) -> str:
    nums = [
        "订单 20260713-000{n}，金额 1,234.{d} 元，折扣 87.{d}% ，余额 -{n}.05。",
        "坐标 N22.{a} E113.{b}，海拔 {n}m，速度 80km/h，温度 -3.{d}C。",
        "客服电话 400-800-{code}，验证码 A{n}B{d}C{a}，请在 05:{m} 前确认。",
        "版本 v3.{d}.{n}-rc.{a}，采样率 24kHz，16-bit，buffer={buf}，RTF=0.{d}{a}。",
    ]
    return nums[i % len(nums)].format(
        n=100 + i,
        d=i % 10,
        a=(i * 7) % 100,
        b=(i * 13) % 100,
        m=str((i * 3) % 60).zfill(2),
        code=str(1000 + i).zfill(4),
        buf=32 + i % 64,
    )


def text_zh_en(i: int) -> str:
    parts = [
        "今天的 build status 是 PASS，但 latency spike 需要继续观察。",
        "请把 Android device 切到 airplane mode，然后 run one more smoke test。",
        "Meeting 结束后同步模型路径 /sdcard/tts/model，并记录 first packet time。",
        "这个 case 覆盖中文、English words、缩写 SDK/TTS/PCM，以及数字 24k。",
    ]
    tail = [
        "If failed, retry after shutdown。",
        "注意 queueMode=PREEMPT，不要和 QUEUE 混用。",
        "Please keep logs under artifacts/run-{i}。",
        "最后检查 speaker、volume 和 languageContext。",
    ]
    return f"{parts[i % len(parts)]}{tail[i % len(tail)].format(i=i)}"


def text_symbols(i: int) -> str:
    samples = [
        "符号集：@#$%^&*()_+-=[]{}|;:'\",.<>/?，以及中文括号《》【】（）——……。",
        "公式 a<=b && b>=c => result!=null；比例 3:2；路径 C:\\tmp\\tts\\out.pcm。",
        "配置 key=value; list=[alpha,beta,gamma]; map={voice:lits-female-02,rate:24k}。",
        "混排符号 foo_bar-baz.qux#frag?x=1&y=2，转义字符 \\\\n \\\\t 仅作为文本。",
    ]
    return f"{samples[i % len(samples)]} Case#{i:03d}."


def text_emoji(i: int) -> str:
    samples = [
        "emoji 混合测试 😀😃😄，状态 good ✅，警告 ⚠️，失败 ❌，重试 🔁。",
        "天气播报：上海 28C ☀️，深圳 31C 🌧️，北京 26C 🌤️，注意防晒 🧴。",
        "流程：开始 ▶️，暂停 ⏸️，停止 ⏹️，录音 🎙️，播放 🔊，保存 💾。",
        "短消息：Hi Mingjie 👋，build finished 🚀，请查看 logs 📄 和 charts 📊。",
    ]
    return f"{samples[i % len(samples)]} 编号 E{i:03d}。"


def text_random(i: int) -> str:
    rng = random.Random(20260713 + i)
    zh = list("随机文本稳定性覆盖边界异常输入输出模型合成播放")
    en = ["alpha", "BETA", "mix", "token", "rand", "TTS", "sdk", "noise"]
    symbols = ["-", "_", "/", ".", ":", "#", "@", "+", "="]
    chunks: list[str] = []
    for _ in range(18 + i % 8):
        kind = rng.choice(["zh", "en", "num", "sym"])
        if kind == "zh":
            chunks.append("".join(rng.choice(zh) for _ in range(rng.randint(1, 4))))
        elif kind == "en":
            chunks.append(rng.choice(en))
        elif kind == "num":
            chunks.append(str(rng.randint(0, 9999)))
        else:
            chunks.append(rng.choice(symbols))
    return "随机串 " + " ".join(chunks) + "。"


def text_code_url_path(i: int) -> str:
    samples = [
        "URL https://example.com/api/v3/speak?id={i}&lang=zh-en#result，requestId=req-{i:04d}。",
        "文件 /sdcard/Android/data/com.lits.tts/files/cache/{i}/audio_{i}.pcm，sha256={hex}。",
        "错误码 E_TTS_{code}，traceId=tr-{hex}-{i:03d}，session=sess_{code}_{i}。",
        "包名 com.lits.tts.sample，类名 TextToSpeechEngineImpl，函数 speak(text, params)。",
    ]
    return samples[i % len(samples)].format(i=i, code=1002300000 + i, hex=f"{(i * 2654435761) & 0xFFFFFFFF:08x}")


def text_punctuation_whitespace(i: int) -> str:
    samples = [
        "停顿测试：你好，世界。Hello, world! 这句后面有多个标点！！！？？？",
        "空格测试：中文  English   123    mixed；tab 用文字表示 <TAB>，换行用 <NL>。",
        "引号测试：“中文双引号”、'single quote'、\"double quote\"、`backtick`。",
        "省略与破折：等等……真的要继续吗——yes, continue; no, stop。",
    ]
    return f"{samples[i % len(samples)]} P{i:03d}。"


TEXT_BUILDERS = {
    "numeric-heavy": text_numeric,
    "zh-en-mixed": text_zh_en,
    "complex-symbols": text_symbols,
    "emoji-mixed": text_emoji,
    "random-text": text_random,
    "code-id-url-path": text_code_url_path,
    "punctuation-whitespace": text_punctuation_whitespace,
}


def make_case(edge_type: str, local_index: int, global_index: int) -> dict[str, Any]:
    params = dict(BASE_PARAMS)
    params.update(profile(global_index))
    operation = operation_for(edge_type, local_index)
    if operation == "synthesize-and-play-route":
        params["playType"] = "SYNTHESIZE_AND_PLAY"
    if operation == "streaming-buffer-cycle":
        params["firstChunkSize"] = 24

    text = TEXT_BUILDERS[edge_type](local_index)
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"text too long for {edge_type}-{local_index}: {len(text)}")

    return {
        "id": f"android-v3-sdk-edge-text-{edge_type}-{local_index:03d}",
        "caseVersion": CASE_VERSION,
        "category": f"edge-{edge_type}",
        "title": f"edge text payload: {edge_type}",
        "operation": operation,
        "expected_status": "PASS",
        "text": text,
        "params": params,
        "setup": {
            "edgeTextType": edge_type,
            "textProfile": edge_type,
            "actualTextLength": len(text),
            "targetTextMaxLength": MAX_TEXT_CHARS,
            "scenarioVariant": local_index,
            "testPoint": f"edge-{edge_type}#{local_index:03d}:{operation}",
            "diversityKey": (
                f"type={edge_type}|op={operation}|len={len(text)}|"
                f"chunk={params['chunkSize']}|speed={params['speed']}|variant={local_index:03d}"
            ),
        },
        "assertions": ASSERTIONS,
        "leak_checks": [],
        "metrics": METRICS,
        "notes": "focused edge text payload; compact PASS-only suite, each text <= 500 chars",
    }


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for edge_type, count in EDGE_COUNTS.items():
        for local_index in range(count):
            cases.append(make_case(edge_type, local_index, len(cases)))
    return cases


def validate(cases: list[dict[str, Any]]) -> None:
    if len(cases) != TOTAL_CASES:
        raise AssertionError(f"expected {TOTAL_CASES} cases, got {len(cases)}")
    ids = [case["id"] for case in cases]
    if len(set(ids)) != len(ids):
        raise AssertionError("duplicate ids found")
    too_long = [(case["id"], len(case["text"])) for case in cases if len(case["text"]) > MAX_TEXT_CHARS]
    if too_long:
        raise AssertionError(f"text length > {MAX_TEXT_CHARS}: {too_long[:3]}")
    counts = Counter(case["setup"]["edgeTextType"] for case in cases)
    if dict(counts) != EDGE_COUNTS:
        raise AssertionError(f"edge type counts mismatch: {dict(counts)}")


def write_outputs(cases: list[dict[str, Any]]) -> None:
    JSONL_PATH.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False, sort_keys=True) for case in cases) + "\n",
        encoding="utf-8",
    )
    lengths = [len(case["text"]) for case in cases]
    operations = Counter(case["operation"] for case in cases)
    summary = {
        "caseVersion": CASE_VERSION,
        "jsonl": JSONL_PATH.name,
        "total": len(cases),
        "maxTextChars": MAX_TEXT_CHARS,
        "edgeTypeCounts": dict(Counter(case["setup"]["edgeTextType"] for case in cases)),
        "categoryCounts": dict(Counter(case["category"] for case in cases)),
        "operationCounts": dict(operations),
        "textLength": {
            "min": min(lengths),
            "max": max(lengths),
            "avg": round(sum(lengths) / len(lengths), 2),
        },
        "notes": "Standalone compact edge-text corpus; Android runner currently whitelists 100/424/1000 sizes unless adjusted.",
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    cases = build_cases()
    validate(cases)
    write_outputs(cases)
    print(f"wrote {len(cases)} cases to {JSONL_PATH}")
    print(f"wrote summary to {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
