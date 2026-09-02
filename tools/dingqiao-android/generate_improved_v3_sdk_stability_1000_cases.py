#!/usr/bin/env python3
"""Generate an improved Dingqiao copy of the Android/Harmony v3 stability suite.

This keeps the existing 1000-case category and operation distribution from the
docs generator, but makes the suite executable for phone stability runs:
ordinary API/state/callback cases use short focused text, only dedicated
longtext/soak/resource cases retain long payloads, long cases get larger
timeouts, and every row carries a unique testPoint/diversityKey.
"""

from __future__ import annotations

import importlib.util
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_GENERATOR = Path(__file__).resolve().with_name("generate_v3_sdk_stability_1000_cases.py")
OUT_DIR = REPO_ROOT / "tts" / "android" / "testdata" / "dingqiao_batch_cases"
JSONL_PATH = OUT_DIR / "android_v3_sdk_stability_1000_cases_improved.jsonl"
SUMMARY_PATH = OUT_DIR / "android_v3_sdk_stability_1000_cases_improved_summary.json"
REDUCED_JSONL_PATH = OUT_DIR / "android_v3_sdk_stability_100_cases_improved_v2.jsonl"
REDUCED_SUMMARY_PATH = OUT_DIR / "android_v3_sdk_stability_100_cases_improved_v2_summary.json"

REDUCED_CATEGORY_COUNTS = {
    "smoke-api": 5,
    "engine-create-query": 7,
    "workpath-resource-load": 7,
    "lifecycle-state-machine": 8,
    "listener-callback-contract": 5,
    "request-queue-scheduler": 8,
    "streaming-config-buffering": 8,
    "playback-channel-audio-route": 6,
    "params-boundary-runtime": 6,
    "error-validation-recovery": 7,
    "memory-leak-soak": 10,
    "fd-thread-process-leak": 8,
    "longtext-tn-stability": 8,
    "stress-recovery-regression": 7,
}

SHORT_PAYLOADS = [
    "SDK 稳定性短载荷，包含 requestId、数字 12345 和日期 2026-07-09。",
    "服务冒烟文本：创建、查询、合成、停止、销毁路径需要稳定完成。",
    "Mixed stability payload with Android, HarmonyOS, 24kHz PCM, and queue PREEMPT.",
    "边界载荷包含 3:05、1,234.56 元、URL https://example.com/a?q=1。",
]

MEDIUM_BLOCKS = [
    "稳定性中等载荷段落，包含中文、English、数字 400-800-1000、单位 24kHz、路径 /sdcard/Android/data/com.lits.tts/files/audio.pcm。",
    "队列与流式场景需要足够文本产生多个 chunk，并让回调、PCM 队列、AudioTrack 生命周期真实发生。",
    "参数组合覆盖 speed、pitch、volume、chunkSize、pcmQueueCapacity、playType、queueMode 与 listener 回调顺序。",
    "TN 载荷包含日期 2026 年 7 月 9 日、金额 1,234.56 元、百分比 87.5%、版本 vocos24k-v3.0.0-rc.1。",
]

LONG_BLOCKS = [
    "长文本稳定性块，包含日期 2026 年 7 月 9 日、金额 1,234.56 元、电话 400-800-1000、百分比 87.5%。",
    "技术片段 https://example.com/release/v3?q=lits#top 与路径 /sdcard/Android/data/com.lits.tts/files/audio.pcm。",
    "混合片段 CPU 87%、24kHz、16-bit、5V2A、版本 vocos24k-v3.0.0-rc.1、队列模式 QUEUE 和 PREEMPT。",
    "播放场景覆盖 SYNTHESIZE_ONLY、SYNTHESIZE_AND_PLAY、AudioTrack 释放、音频焦点丢失、锁屏后台恢复。",
]


def load_source_cases() -> list[dict[str, Any]]:
    spec = importlib.util.spec_from_file_location("source_stability_generator", SOURCE_GENERATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {SOURCE_GENERATOR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.CASES.clear()
    module.build_cases()
    module.validate()
    return deepcopy(module.CASES)


def repeat_to_length(prefix: str, blocks: list[str], target: int, seed: int) -> str:
    text = prefix
    j = seed
    while len(text) < target:
        text += blocks[j % len(blocks)]
        j += 1
    if len(text) == target:
        return text
    return text[: target - 1] + "。"


def text_for_case(case: dict[str, Any], index: int) -> tuple[str, str, int | None]:
    category = case["category"]
    operation = case["operation"]

    if category == "error-validation-recovery":
        variant = case.get("setup", {}).get("validationVariant", "")
        if case.get("expectedErrorName") == "TEXT_LENGTH_INVALID":
            return case["text"], "error-invalid-text", None
        if str(variant).startswith("overlong-"):
            return case["text"], "error-overlong", len(case["text"])
        target = [48, 72, 96][index % 3]
        return repeat_to_length(f"错误恢复合法上下文 {index + 1}。", MEDIUM_BLOCKS, target, index), "error-recovery-medium", target

    if category == "longtext-tn-stability":
        target = [600, 900, 1200, 1800, 2600, 3600][index % 6]
        return repeat_to_length(f"长文本 TN 稳定性样例 {index + 1}。", LONG_BLOCKS, target, index), "long-tn", target

    if category == "streaming-config-buffering":
        target = [80, 120, 180, 260, 360][index % 5]
        return repeat_to_length(f"流式缓冲稳定性样例 {index + 1}。", MEDIUM_BLOCKS, target, index), "streaming-medium", target

    if category == "request-queue-scheduler":
        target = [40, 56, 72, 96, 128][index % 5]
        return repeat_to_length(f"队列调度稳定性样例 {index + 1}。", MEDIUM_BLOCKS, target, index), "queue-mixed", target

    if category == "playback-channel-audio-route":
        target = [48, 72, 96, 140][index % 4]
        return repeat_to_length(f"播放路由稳定性样例 {index + 1}。", MEDIUM_BLOCKS, target, index), "playback-medium", target

    if category == "memory-leak-soak":
        if operation == "longtext-repeat-loop":
            target = [600, 1000, 1600][index % 3]
            return repeat_to_length(f"内存 soak 长文本循环样例 {index + 1}。", LONG_BLOCKS, target, index), "soak-long", target
        target = [48, 72, 120, 200][index % 4]
        return repeat_to_length(f"内存 soak 稳定性样例 {index + 1}。", MEDIUM_BLOCKS, target, index), "soak-mixed", target

    if category == "fd-thread-process-leak":
        target = [72, 120, 240, 420][index % 4]
        return repeat_to_length(f"FD 线程进程泄漏样例 {index + 1}。", LONG_BLOCKS, target, index), "resource-leak-tn", target

    if category == "stress-recovery-regression":
        target = [80, 140, 260, 420][index % 4]
        return repeat_to_length(f"回归恢复压力样例 {index + 1}。", LONG_BLOCKS, target, index), "stress-recovery", target

    if category in {"lifecycle-state-machine", "listener-callback-contract"}:
        target = [36, 48, 64, 96][index % 4]
        return repeat_to_length(f"生命周期回调稳定性样例 {index + 1}。", MEDIUM_BLOCKS, target, index), "state-callback-mixed", target

    if category in {"engine-create-query", "workpath-resource-load", "params-boundary-runtime"}:
        target = [36, 48, 64][index % 3]
        return repeat_to_length(f"SDK 参数资源稳定性样例 {index + 1}。", SHORT_PAYLOADS + MEDIUM_BLOCKS, target, index), "api-resource-short", target

    target = [32, 48, 64][index % 3]
    return repeat_to_length(f"SDK 冒烟稳定性样例 {index + 1}。", SHORT_PAYLOADS, target, index), "smoke-short", target


def tune_timeout(case: dict[str, Any], text_len: int) -> None:
    """Set timeouts from scenario cost instead of using one bucket per category."""
    params = dict(case.get("params", {}))
    category = case["category"]
    operation = case["operation"]
    speed = float(params.get("speed", 1.0) or 1.0)
    slow_factor = max(1.0, 1.0 / max(speed, 0.25))

    if case.get("expectedErrorName") == "TEXT_LENGTH_INVALID":
        timeout_ms = 60_000
    elif category == "longtext-tn-stability":
        timeout_ms = int(min(600_000, max(180_000, 90_000 + text_len * 120 * slow_factor)))
    elif category == "memory-leak-soak" and operation == "longtext-repeat-loop":
        timeout_ms = int(min(480_000, max(180_000, 90_000 + text_len * 100 * slow_factor)))
    elif category in {"memory-leak-soak", "fd-thread-process-leak", "stress-recovery-regression"}:
        timeout_ms = int(min(360_000, max(120_000, 75_000 + text_len * 60 * slow_factor)))
    elif category in {"request-queue-scheduler", "playback-channel-audio-route"}:
        timeout_ms = int(min(240_000, max(90_000, 60_000 + text_len * 80 * slow_factor)))
    elif category == "streaming-config-buffering":
        timeout_ms = int(min(180_000, max(90_000, 60_000 + text_len * 70 * slow_factor)))
    else:
        timeout_ms = int(min(120_000, max(45_000, 30_000 + text_len * 50 * slow_factor)))

    params["timeoutMs"] = timeout_ms
    case["params"] = params


def tune_first_chunk(case: dict[str, Any]) -> None:
    """Keep large steady-state chunks while making first-packet latency intentional."""
    params = dict(case.get("params", {}))
    category = case["category"]
    chunk_size = int(params.get("chunkSize", 50) or 50)
    if category == "streaming-config-buffering" and chunk_size > 64:
        params["firstChunkSize"] = 32
    elif category in {"longtext-tn-stability", "memory-leak-soak", "fd-thread-process-leak"} and chunk_size > 64:
        params["firstChunkSize"] = 50
    else:
        params.pop("firstChunkSize", None)
    case["params"] = params


def add_unique_test_point(case: dict[str, Any], category_index: int) -> None:
    params = case.get("params", {})
    setup = case.get("setup", {})
    interesting = [
        f"op={case.get('operation')}",
        f"play={params.get('playType', 'SYNTHESIZE_ONLY')}",
        f"queue={params.get('queueMode', 'PREEMPT')}",
        f"chunk={params.get('chunkSize')}",
        f"first={params.get('firstChunkSize', params.get('streamingFirstChunkSize'))}",
        f"pcmCap={params.get('pcmQueueCapacity')}",
        f"speed={params.get('speed')}",
        f"source={params.get('modelSource', 'offline')}",
        f"profile={setup.get('textProfile')}",
        f"len={setup.get('actualTextLength')}",
    ]
    if "requestBurstSize" in params:
        interesting += [f"burst={params.get('requestBurstSize')}", f"interval={setup.get('burstIntervalMs')}"]
    if "soundChannel" in params:
        interesting += [f"sound={params.get('soundChannel')}", f"focus={setup.get('audioFocusScenario')}"]
    if case.get("expected_status") == "EXPECTED_ERROR":
        interesting += [f"expectedError={case.get('expectedErrorName')}"]
    interesting += [f"variant={category_index:03d}"]
    diversity_key = "|".join(str(item) for item in interesting)
    setup["testPoint"] = f"{case['category']}#{category_index:03d}:{case['operation']}"
    setup["scenarioVariant"] = category_index
    setup["diversityKey"] = diversity_key
    case["setup"] = setup


def expected_counts(case: dict[str, Any]) -> dict[str, Any]:
    params = case.get("params", {})
    setup = case.get("setup", {})
    counts: dict[str, Any] = {}
    if "loopCount" in params:
        counts["expectedLoopCount"] = params["loopCount"]
    if "requestBurstSize" in params:
        counts["expectedSubmittedRequests"] = params["requestBurstSize"]
        counts["expectedTerminalCallbacks"] = params["requestBurstSize"]
        counts["requireQueueDepthZero"] = True
    if setup.get("runValidRequestAfterError"):
        counts["validRecoveryRequestCount"] = max(1, int(setup.get("validRecoveryRequestCount", 1)))
    if setup.get("repeatInSameEngine"):
        counts["expectedRepeatInSameEngine"] = setup["repeatInSameEngine"]
    return counts


def strengthen_case(case: dict[str, Any], global_index: int, category_index: int) -> dict[str, Any]:
    new = deepcopy(case)
    text, profile, target = text_for_case(new, category_index)
    new["text"] = text
    setup = dict(new.get("setup", {}))
    setup["textProfile"] = profile
    setup["actualTextLength"] = len(text)
    if target is not None:
        setup["targetTextLength"] = target
        setup["textLengthToleranceRatio"] = 0.1
    setup.update(expected_counts(new))

    category = new["category"]
    if category in {"streaming-config-buffering", "longtext-tn-stability"}:
        setup.setdefault("minChunkCount", 2 if len(text) < 800 else 5)
        setup.setdefault("minAudioBytes", 4096)
    if category in {"playback-channel-audio-route", "memory-leak-soak", "fd-thread-process-leak"}:
        setup.setdefault("requireResourceSnapshotBeforeAfter", True)
    if category in {"workpath-resource-load", "fd-thread-process-leak", "longtext-tn-stability"}:
        setup.setdefault("forceShutdownAtEnd", True)
    if category == "memory-leak-soak":
        setup.setdefault("requireTrendSample", True)
    if category == "fd-thread-process-leak":
        setup.setdefault("requireProcSnapshot", True)
    if category == "stress-recovery-regression":
        setup.setdefault("requireRecoveryRequestSuccess", True)

    new["setup"] = setup
    tune_timeout(new, len(text))
    tune_first_chunk(new)
    add_unique_test_point(new, category_index)
    new["notes"] = "improved-dingqiao-payload-v1"
    new["caseVersion"] = "dingqiao-stability-improved-v2"
    new["sourceCaseIndex"] = global_index
    return new


def validate(cases: list[dict[str, Any]]) -> None:
    if len(cases) != 1000:
        raise AssertionError(f"expected 1000 cases, got {len(cases)}")
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise AssertionError("duplicate ids")
    counts = Counter(case["category"] for case in cases)
    if sum(counts.values()) != 1000:
        raise AssertionError(f"bad category counts: {counts}")

    required = {"id", "category", "operation", "expected_status", "text", "params", "setup", "assertions", "leak_checks", "metrics"}
    for case in cases:
        missing = required - set(case)
        if missing:
            raise AssertionError(f"{case.get('id')} missing {sorted(missing)}")
        if case["expected_status"] == "EXPECTED_ERROR":
            if "expectedErrorName" not in case or "expectedErrorCode" not in case:
                raise AssertionError(f"{case['id']} missing expected error fields")

    for case in cases:
        setup = case["setup"]
        target = setup.get("targetTextLength")
        if target and case.get("expectedErrorName") != "TEXT_LENGTH_INVALID":
            actual = len(case["text"])
            tolerance = max(1, int(target * setup.get("textLengthToleranceRatio", 0.1)))
            if abs(actual - target) > tolerance:
                raise AssertionError(f"{case['id']} text length {actual} not near target {target}")

    long_cases = [case for case in cases if case["category"] == "longtext-tn-stability"]
    if min(len(case["text"]) for case in long_cases) < 600:
        raise AssertionError("longtext-tn-stability contains short text")
    streaming_cases = [case for case in cases if case["category"] == "streaming-config-buffering"]
    if max(len(case["text"]) for case in streaming_cases) > 400:
        raise AssertionError("streaming-config-buffering contains too-long text")

    duplicate_points = [
        case["id"] for case in cases
        if "diversityKey" not in case.get("setup", {})
    ]
    if duplicate_points:
        raise AssertionError(f"missing diversityKey: {duplicate_points[:5]}")

    seen_points: set[str] = set()
    repeated: list[str] = []
    for case in cases:
        key = f"{case['category']}|{case['setup']['diversityKey']}"
        if key in seen_points:
            repeated.append(case["id"])
        seen_points.add(key)
    if repeated:
        raise AssertionError(f"duplicate test points: {repeated[:10]}")
        raise AssertionError("streaming-config-buffering contains too-short text")


def write_outputs(cases: list[dict[str, Any]]) -> None:
    with JSONL_PATH.open("w", encoding="utf-8") as f:
        for case in cases:
            f.write(json.dumps(case, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    by_category = {}
    for category in sorted({case["category"] for case in cases}):
        rows = [case for case in cases if case["category"] == category]
        lengths = [len(case["text"]) for case in rows]
        by_category[category] = {
            "count": len(rows),
            "minTextLength": min(lengths),
            "maxTextLength": max(lengths),
            "avgTextLength": round(sum(lengths) / len(lengths), 2),
            "leakCheckCases": sum(bool(case.get("leak_checks")) for case in rows),
        }
    summary = {
        "total": len(cases),
        "jsonl": JSONL_PATH.name,
        "sourceGenerator": str(SOURCE_GENERATOR.relative_to(REPO_ROOT)),
        "caseVersion": "dingqiao-stability-improved-v2",
        "categorySummary": by_category,
        "statusCounts": dict(Counter(case["expected_status"] for case in cases)),
        "operationCount": len(set(case["operation"] for case in cases)),
        "improvements": [
            "ordinary API/state/callback/queue/playback cases use short focused text",
            "long text is retained only for longtext, long-soak, selected resource, and stress scenarios",
            "timeouts are tuned from text length, speed, and scenario cost",
            "setup contains actualTextLength, textProfile, expected loop/burst counts, and resource snapshot requirements",
            "setup contains testPoint and diversityKey to avoid duplicate scenario intent",
            "error cases preserve invalid text payloads while strengthening recovery-context payloads",
        ],
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def select_reduced_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for category, target_count in REDUCED_CATEGORY_COUNTS.items():
        rows = [case for case in cases if case["category"] == category]
        by_operation: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_operation.setdefault(row["operation"], []).append(row)

        bucket_names = sorted(by_operation)
        bucket_offsets = {name: 0 for name in bucket_names}
        category_selected: list[dict[str, Any]] = []
        while len(category_selected) < target_count:
            progressed = False
            for name in bucket_names:
                offset = bucket_offsets[name]
                bucket = by_operation[name]
                if offset < len(bucket) and len(category_selected) < target_count:
                    category_selected.append(deepcopy(bucket[offset]))
                    bucket_offsets[name] += 1
                    progressed = True
            if not progressed:
                break
        if len(category_selected) != target_count:
            raise AssertionError(f"{category} selected {len(category_selected)} / {target_count}")
        selected.extend(category_selected)

    if len(selected) != 100:
        raise AssertionError(f"reduced suite expected 100, got {len(selected)}")
    ids = [case["id"] for case in selected]
    if len(ids) != len(set(ids)):
        raise AssertionError("reduced suite has duplicate ids")
    return selected


def write_reduced_outputs(cases: list[dict[str, Any]]) -> None:
    with REDUCED_JSONL_PATH.open("w", encoding="utf-8") as f:
        for case in cases:
            f.write(json.dumps(case, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    by_category = {}
    for category in sorted({case["category"] for case in cases}):
        rows = [case for case in cases if case["category"] == category]
        lengths = [len(case["text"]) for case in rows]
        by_category[category] = {
            "count": len(rows),
            "minTextLength": min(lengths),
            "maxTextLength": max(lengths),
            "avgTextLength": round(sum(lengths) / len(lengths), 2),
            "operations": sorted(set(case["operation"] for case in rows)),
        }
    summary = {
        "total": len(cases),
        "jsonl": REDUCED_JSONL_PATH.name,
        "sourceJsonl": JSONL_PATH.name,
        "caseVersion": "dingqiao-stability-improved-v2-reduced100",
        "categorySummary": by_category,
        "statusCounts": dict(Counter(case["expected_status"] for case in cases)),
        "categoryCounts": dict(Counter(case["category"] for case in cases)),
        "selectionPolicy": "round-robin by operation within fixed category quotas",
    }
    REDUCED_SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    source_cases = load_source_cases()
    category_seen: Counter[str] = Counter()
    improved: list[dict[str, Any]] = []
    for global_index, case in enumerate(source_cases):
        category = case["category"]
        category_index = category_seen[category]
        category_seen[category] += 1
        improved.append(strengthen_case(case, global_index, category_index))
    validate(improved)
    write_outputs(improved)
    reduced = select_reduced_cases(improved)
    write_reduced_outputs(reduced)
    print(f"wrote {len(improved)} cases")
    print(JSONL_PATH)
    print(SUMMARY_PATH)
    print(f"wrote {len(reduced)} reduced cases")
    print(REDUCED_JSONL_PATH)
    print(REDUCED_SUMMARY_PATH)


if __name__ == "__main__":
    main()
