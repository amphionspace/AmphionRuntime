#!/usr/bin/env python3
"""Generate a 1000-case Android/Harmony v3.0 SDK runtime-stability suite.

Runtime stability only: crash/hang/leak/lifecycle/queue/streaming/playback/
error-recovery. Text is a service payload, never a pronunciation target.

The industrial design doc is hand-maintained at:
ANDROID_V3_SDK_STABILITY_1000_CASE_DESIGN.md
This generator writes JSONL + summary only and must not overwrite that doc.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "tts" / "android" / "testdata" / "dingqiao_batch_cases"
JSONL_PATH = OUT_DIR / "android_v3_sdk_stability_1000_cases.jsonl"
SUMMARY_PATH = OUT_DIR / "android_v3_sdk_stability_1000_summary.json"
REPORT_PATH = OUT_DIR / "ANDROID_V3_SDK_STABILITY_1000_CASE_DESIGN.md"

COUNTS: dict[str, int] = {
    "smoke-api": 25,
    "engine-create-query": 75,
    "workpath-resource-load": 75,
    "lifecycle-state-machine": 85,
    "listener-callback-contract": 55,
    "request-queue-scheduler": 80,
    "streaming-config-buffering": 80,
    "playback-channel-audio-route": 45,
    "params-boundary-runtime": 65,
    "error-validation-recovery": 75,
    "longtext-tn-stability": 80,
    "memory-leak-soak": 110,
    "fd-thread-process-leak": 90,
    "stress-recovery-regression": 60,
}

ERROR_CODES = {
    "TEXT_LENGTH_INVALID": 1002300001,
    "LANGUAGE_UNSUPPORTED": 1002300002,
    "VOICE_UNSUPPORTED": 1002300003,
    "CREATE_ENGINE_FAILED": 1002300005,
    "ENGINE_LIMIT_REACHED": 1002300006,
    "ENGINE_NOT_INITIALIZED": 1002300007,
    "ENGINE_DESTROYED": 1002300008,
    "INTERNAL_SERVICE_ERROR": 1002300009,
    "RUNTIME_EXCEPTION": 1002300011,
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
    "timeoutMs": 60000,
}

TEXT_PAYLOADS = [
    "SDK service stability payload with number 12345 and date 2026-07-08.",
    "服务稳定性测试文本，包含 3:05、1,234.56 元和 URL https://example.com/a?q=1。",
    "Mixed payload: Android TTS queueMode PREEMPT, chunkSize 50, requestId LITS-42。",
    "长文本块包含中文、English、数字 400-800-1000、单位 24kHz 和特殊符号 …… 😀。",
]

LEAK_CHECKS = [
    "java_heap_delta_below_threshold",
    "native_heap_delta_below_threshold",
    "rss_delta_below_threshold",
    "fd_count_returns_near_baseline",
    "thread_count_returns_near_baseline",
    "tn_child_process_count_returns_near_baseline",
    "stderr_watcher_thread_not_accumulating",
    "no_zombie_or_orphan_tn_process",
]

CASES: list[dict[str, Any]] = []


def profile(i: int) -> dict[str, Any]:
    profiles = [
        {"speed": 1.0, "pitch": 1.0, "volume": 1.0, "chunkSize": 50, "pcmQueueCapacity": 32},
        {"speed": 0.75, "pitch": 0.8, "volume": 0.8, "chunkSize": 32, "pcmQueueCapacity": 8},
        {"speed": 1.25, "pitch": 1.2, "volume": 1.2, "chunkSize": 64, "pcmQueueCapacity": 16},
        {"speed": 1.5, "pitch": 1.0, "volume": 0.6, "chunkSize": 100, "pcmQueueCapacity": 4},
        {"speed": 0.5, "pitch": 1.0, "volume": 1.5, "chunkSize": 128, "pcmQueueCapacity": 2},
    ]
    return profiles[i % len(profiles)]


def payload(i: int) -> str:
    return f"{TEXT_PAYLOADS[i % len(TEXT_PAYLOADS)]} case={i + 1}."


def add_case(
    category: str,
    local_index: int,
    *,
    title: str,
    operation: str,
    text: str | None = None,
    params: dict[str, Any] | None = None,
    setup: dict[str, Any] | None = None,
    assertions: list[str] | None = None,
    leak_checks: list[str] | None = None,
    expected_status: str = "PASS",
    expected_error_name: str | None = None,
    notes: str = "",
) -> None:
    merged = dict(BASE_PARAMS)
    merged.update(profile(local_index))
    if params:
        merged.update(params)
    case = {
        "id": f"android-v3-sdk-stability-{category}-{local_index:03d}",
        "category": category,
        "title": title,
        "operation": operation,
        "expected_status": expected_status,
        "text": payload(local_index) if text is None else text,
        "params": merged,
        "setup": setup or {},
        "assertions": assertions or ["no_crash", "no_unexpected_error", "complete_callback", "terminal_state_observed"],
        "leak_checks": leak_checks or [],
        "metrics": [
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
        ],
        "notes": notes,
    }
    if expected_error_name is not None:
        case["expectedErrorName"] = expected_error_name
        case["expectedErrorCode"] = ERROR_CODES[expected_error_name]
        case["assertions"] = [
            "error_callback_or_throw_observed",
            "exact_error_code_matches",
            "no_crash",
            "service_accepts_next_valid_request_after_error",
            "no_resource_leak_after_error",
        ]
    CASES.append(case)


def build_smoke_api() -> None:
    scenarios = [
        "cold-create-speak", "warm-create-speak", "query-all-voices", "query-zh-voices", "query-en-voices",
        "default-params", "set-listener-before-speak", "speak-with-request-id", "synthesize-only",
        "synthesize-and-play", "shutdown-after-speak", "recreate-after-shutdown", "is-busy-before-speak",
        "is-busy-during-speak", "is-busy-after-complete", "stop-idle", "stop-active", "double-stop",
        "double-shutdown", "deferred-model-load", "create-second-engine", "create-third-engine",
        "voice-query-after-engine-create", "voice-query-after-shutdown", "next-valid-after-smoke-sequence",
    ]
    for i, name in enumerate(scenarios):
        add_case("smoke-api", i, title="basic SDK smoke stability", operation=name, setup={"smokeVariant": name})


def build_engine_create_query() -> None:
    languages = ["zh-en", "en-US", "zh-CN"]
    model_sources = ["bundled", "external", "default"]
    for i in range(COUNTS["engine-create-query"]):
        op = ["create-engine", "query-voices", "create-query-destroy", "deferred-load-create", "multi-engine-sequential"][i % 5]
        add_case(
            "engine-create-query",
            i,
            title="engine create and query stability",
            operation=op,
            params={"language": languages[i % len(languages)], "modelSource": model_sources[i % len(model_sources)], "modelLoadOnCreate": i % 4 != 0},
            setup={"engineName": f"stability-engine-{i:03d}", "voiceQueryRequestId": f"voice-query-{i:03d}", "destroyAtEnd": True},
            assertions=["engine_create_or_query_success", "no_crash", "no_unexpected_error", "engine_destroy_releases_runtime"],
            leak_checks=["native_heap_delta_below_threshold", "fd_count_returns_near_baseline"] if i % 3 == 0 else [],
        )


def build_workpath_resource_load() -> None:
    scenarios = ["bundled-default", "external-valid", "empty-workpath-default", "switch-before-create", "set-workpath-after-shutdown", "manifest-version-check", "model-info-consistency", "profile-info-consistency"]
    for i in range(COUNTS["workpath-resource-load"]):
        scenario = scenarios[i % len(scenarios)]
        add_case(
            "workpath-resource-load",
            i,
            title="workPath and resource loading stability",
            operation="resource-load-cycle",
            params={"workPathScenario": scenario, "modelLoadOnCreate": i % 2 == 0},
            setup={"resourceScenario": scenario, "repeatCreateDestroy": 1 + (i % 4), "setWorkPathTiming": ["before-create", "after-create-idle", "after-shutdown"][i % 3]},
            assertions=["no_crash", "resource_load_success", "model_info_matches_manifest", "shutdown_releases_resource_handles"],
            leak_checks=["fd_count_returns_near_baseline", "native_heap_delta_below_threshold"],
        )


def build_lifecycle_state_machine() -> None:
    ops = ["speak-before-listener", "speak-after-listener", "stop-idle", "stop-running", "stop-queued", "shutdown-idle", "shutdown-running", "speak-after-shutdown", "set-listener-after-shutdown", "is-busy-transitions"]
    for i in range(COUNTS["lifecycle-state-machine"]):
        op = ops[i % len(ops)]
        expected_error = "ENGINE_DESTROYED" if "after-shutdown" in op else None
        add_case(
            "lifecycle-state-machine",
            i,
            title="lifecycle state-machine stability",
            operation=op,
            params={"queueMode": "QUEUE" if i % 4 == 0 else "PREEMPT"},
            setup={"preState": ["new", "idle", "running", "queued", "destroyed"][i % 5], "repeat": 1 + (i % 5)},
            assertions=["state_transition_matches_contract", "terminal_callback_once_or_expected_error", "no_deadlock", "isBusy_matches_state"],
            leak_checks=["thread_count_returns_near_baseline"] if i % 2 == 0 else [],
            expected_status="EXPECTED_ERROR" if expected_error else "PASS",
            expected_error_name=expected_error,
        )


def build_listener_callback_contract() -> None:
    ops = ["replace-listener-idle", "replace-listener-running", "null-listener-then-speak", "late-listener-registration", "callback-order", "callback-on-error", "callback-threading", "listener-reuse-after-shutdown"]
    for i in range(COUNTS["listener-callback-contract"]):
        op = ops[i % len(ops)]
        add_case(
            "listener-callback-contract",
            i,
            title="listener and callback contract stability",
            operation=op,
            setup={"listenerVariant": op, "replaceAtChunk": i % 7, "expectedTerminalCallbacks": 1},
            assertions=["no_crash", "callback_order_valid", "terminal_callback_once_per_request", "listener_reference_not_leaked"],
            leak_checks=["java_heap_delta_below_threshold", "thread_count_returns_near_baseline"] if i % 3 == 0 else [],
        )


def build_request_queue_scheduler() -> None:
    ops = ["preempt-burst", "queue-burst", "mixed-preempt-queue", "reentrant-submit", "stop-during-burst", "shutdown-during-burst", "duplicate-id-burst", "back-to-back-short"]
    for i in range(COUNTS["request-queue-scheduler"]):
        op = ops[i % len(ops)]
        add_case(
            "request-queue-scheduler",
            i,
            title="request queue scheduler stability",
            operation=op,
            params={"queueMode": "QUEUE" if "queue" in op else "PREEMPT", "requestBurstSize": [2, 3, 5, 8, 13][i % 5], "timeoutMs": 120000},
            setup={"burstIntervalMs": [0, 5, 20, 100][i % 4], "stopAtRequest": i % 6 if "stop" in op else None},
            assertions=["no_crash", "scheduler_no_deadlock", "terminal_callback_once_per_request", "queue_depth_returns_zero"],
            leak_checks=["thread_count_returns_near_baseline", "fd_count_returns_near_baseline"],
        )


def build_streaming_config_buffering() -> None:
    for i in range(COUNTS["streaming-config-buffering"]):
        api_path = ["builder-api", "extraParams", "alias-firstChunkSize", "alias-pcmQueueSize", "conflict-streamingConfig-extraParams"][i % 5]
        add_case(
            "streaming-config-buffering",
            i,
            title="streaming config and buffering stability",
            operation="streaming-buffer-cycle",
            params={
                "chunkSize": [16, 25, 32, 50, 64, 100, 128, 256][i % 8],
                "firstChunkSize": [8, 16, 25, 50, 100][i % 5],
                "streamingFirstChunkSize": [8, 16, 25, 50, 100][(i + 2) % 5],
                "pcmQueueCapacity": [1, 2, 3, 4, 8, 16, 32][i % 7],
                "streamingConfigApiPath": api_path,
            },
            setup={"configConflictExpectedWinner": "streamingConfig" if "conflict" in api_path else "single-source", "runChunksToCompletion": True},
            assertions=["no_crash", "chunk_sequence_contiguous", "first_chunk_rule_applied", "pcm_queue_no_deadlock"],
            leak_checks=["fd_count_returns_near_baseline"],
        )


def build_playback_channel_audio_route() -> None:
    channels = [None, "default", "music", "alarm", "notification", "ring", "system", "invalid-channel", "", " MUSIC "]
    for i in range(COUNTS["playback-channel-audio-route"]):
        channel = channels[i % len(channels)]
        invalid = channel in {"invalid-channel", "", " MUSIC "}
        add_case(
            "playback-channel-audio-route",
            i,
            title="soundChannel and playback route stability",
            operation="synthesize-and-play-route",
            params={"playType": "SYNTHESIZE_AND_PLAY", "soundChannel": channel, "timeoutMs": 120000},
            setup={"audioFocusScenario": ["normal", "focus-loss", "focus-duck", "screen-off"][i % 4]},
            assertions=["no_crash", "playback_complete_or_controlled_error", "audio_track_released"],
            leak_checks=["fd_count_returns_near_baseline", "thread_count_returns_near_baseline"],
            expected_status="EXPECTED_ERROR" if invalid else "PASS",
            expected_error_name="RUNTIME_EXCEPTION" if invalid else None,
        )


def build_params_boundary_runtime() -> None:
    speeds = [0.1, 0.25, 0.49, 0.5, 0.75, 1.0, 1.5, 2.0, 2.01, 3.0]
    pitches = [0.5, 0.75, 1.0, 1.25, 2.0]
    volumes = [0.0, 0.25, 0.6, 1.0, 1.5, 2.0]
    for i in range(COUNTS["params-boundary-runtime"]):
        add_case(
            "params-boundary-runtime",
            i,
            title="runtime parameter boundary stability",
            operation="parameter-boundary-speak",
            params={"speed": speeds[i % len(speeds)], "pitch": pitches[i % len(pitches)], "volume": volumes[i % len(volumes)], "timeoutMs": 90000},
            setup={"paramApplyTiming": ["before-speak", "during-queue", "after-stop"][i % 3]},
            assertions=["no_crash", "complete_callback", "effective_param_reported_or_clamped", "next_request_still_succeeds"],
        )


def build_error_validation_recovery() -> None:
    specs: list[tuple[str, str, dict[str, Any], str, str]] = []
    for label, text in [("empty", ""), ("space", " "), ("tab-newline", "\t\n"), ("fullwidth-space", "\u3000")]:
        specs.append(("speak", "TEXT_LENGTH_INVALID", {}, text, label))
    for length in [10001, 10050, 12000, 20000]:
        specs.append(("speak", "TEXT_LENGTH_INVALID", {}, "长" * length, f"overlong-{length}"))
    for value in ["", " ", "bad-voice", "unknown_voice", "zh-male-missing"]:
        specs.append(("create-engine", "VOICE_UNSUPPORTED", {"voiceId": value}, payload(len(specs)), f"voice-{value!r}"))
    for value in ["", " ", "zh-CN", "english", "xx-YY"]:
        specs.append(("create-engine", "LANGUAGE_UNSUPPORTED", {"language": value}, payload(len(specs)), f"language-{value!r}"))
    for value in ["ONLINE", "cloud", "remote", "internet"]:
        specs.append(("create-engine", "CREATE_ENGINE_FAILED", {"modelSource": value}, payload(len(specs)), f"modelSource-{value}"))
    for value in ["", " ", "\n"]:
        specs.append(("create-engine", "CREATE_ENGINE_FAILED", {"engineName": value}, payload(len(specs)), f"engineName-{value!r}"))
    for value in ["missing-manifest", "broken-manifest", "missing-model", "corrupt-model", "empty-work-path", "permission-denied-work-path"]:
        specs.append(("create-engine", "CREATE_ENGINE_FAILED", {"workPathScenario": value}, payload(len(specs)), f"workPath-{value}"))
    for value in [0.0, 0.1, 0.49, 2.01, 3.0, 10.0]:
        specs.append(("speak", "RUNTIME_EXCEPTION", {"pitch": value}, payload(len(specs)), f"pitch-{value}"))
    for value in [-1.0, -0.01, 2.01, 3.0, 10.0]:
        specs.append(("speak", "RUNTIME_EXCEPTION", {"volume": value}, payload(len(specs)), f"volume-{value}"))
    for value in ["wav", "mp3", "aac", "PCM", "", " pcm "]:
        specs.append(("speak", "RUNTIME_EXCEPTION", {"audioType": value}, payload(len(specs)), f"audioType-{value!r}"))
    for value in ["", " ", "\n", "\t", "\u3000"]:
        specs.append(("speak", "RUNTIME_EXCEPTION", {"requestId": value}, payload(len(specs)), f"requestId-{value!r}"))
    for i in range(12):
        specs.append(("duplicate-request-id-pair", "RUNTIME_EXCEPTION", {"requestId": f"duplicate-id-{i:02d}"}, payload(len(specs)), f"duplicate-id-{i:02d}"))
    for i in range(7):
        specs.append(("speak-after-shutdown", "ENGINE_DESTROYED", {"requestId": f"destroyed-id-{i:02d}"}, payload(len(specs)), f"destroyed-{i:02d}"))
    for i in range(3):
        specs.append(("create-engine-burst", "ENGINE_LIMIT_REACHED", {"engineCreateCount": 4 + i}, payload(len(specs)), f"engine-limit-{4+i}"))
    if len(specs) != COUNTS["error-validation-recovery"]:
        raise AssertionError(f"error-validation-recovery specs mismatch: {len(specs)}")
    for i, (op, err, params, text, label) in enumerate(specs):
        add_case(
            "error-validation-recovery",
            i,
            title="controlled error and recovery stability",
            operation=op,
            text=text,
            params=params,
            setup={"validationVariant": label, "runValidRequestAfterError": True},
            expected_status="EXPECTED_ERROR",
            expected_error_name=err,
            leak_checks=["fd_count_returns_near_baseline", "thread_count_returns_near_baseline"],
        )


def long_text(i: int, target: int) -> str:
    blocks = [
        "长文本稳定性块，包含日期 2026 年 7 月 8 日、金额 1,234.56 元、电话 400-800-1000。",
        "技术片段 https://example.com/release/v3?q=lits#top 与路径 /sdcard/Android/data/com.lits.tts/files/audio.pcm。",
        "混合片段 CPU 87%、24kHz、16-bit、5V2A、版本 vocos24k-v2.5.0-rc.1。",
    ]
    text = f"长文本服务稳定性样例 {i + 1}。"
    j = i
    while len(text) < target:
        text += blocks[j % len(blocks)]
        j += 1
    return text[: target - 1] + "。"


def build_longtext_tn_stability() -> None:
    lengths = [800, 1500, 3000, 5000, 8000, 9500]
    for i in range(COUNTS["longtext-tn-stability"]):
        add_case(
            "longtext-tn-stability",
            i,
            title="long text and TN service stability",
            operation="longtext-speak",
            text=long_text(i, lengths[i % len(lengths)]),
            params={"playType": "SYNTHESIZE_AND_PLAY" if i % 5 == 0 else "SYNTHESIZE_ONLY", "queueMode": "QUEUE" if i % 7 == 0 else "PREEMPT", "timeoutMs": 180000},
            setup={"targetTextLength": lengths[i % len(lengths)], "repeatInSameEngine": 1 + (i % 3)},
            assertions=["no_crash", "no_unexpected_error", "complete_callback", "tn_process_no_broken_pipe", "next_short_request_succeeds"],
            leak_checks=["fd_count_returns_near_baseline", "tn_child_process_count_stable", "stderr_watcher_thread_not_accumulating"],
        )


def build_memory_leak_soak() -> None:
    ops = ["create-speak-shutdown-loop", "same-engine-repeat-speak", "longtext-repeat-loop", "error-then-valid-loop", "playback-repeat-loop", "deferred-load-loop"]
    for i in range(COUNTS["memory-leak-soak"]):
        op = ops[i % len(ops)]
        add_case(
            "memory-leak-soak",
            i,
            title="memory leak soak stability",
            operation=op,
            params={"loopCount": [10, 20, 50, 100][i % 4], "timeoutMs": 240000, "playType": "SYNTHESIZE_AND_PLAY" if "playback" in op else "SYNTHESIZE_ONLY"},
            setup={"gcAfterLoop": True, "sampleMemoryEveryNRequests": [1, 5, 10][i % 3], "baselineWarmupRequests": 2},
            assertions=["no_crash", "loop_completes", "memory_growth_below_threshold", "post_gc_memory_near_baseline"],
            leak_checks=["java_heap_delta_below_threshold", "native_heap_delta_below_threshold", "rss_delta_below_threshold"],
        )


def build_fd_thread_process_leak() -> None:
    ops = ["tn-fork-loop", "create-shutdown-fd-loop", "streaming-pipe-loop", "stderr-watcher-loop", "playback-audiotrack-loop", "error-path-fd-loop"]
    for i in range(COUNTS["fd-thread-process-leak"]):
        op = ops[i % len(ops)]
        add_case(
            "fd-thread-process-leak",
            i,
            title="fd thread process leak stability",
            operation=op,
            params={"loopCount": [10, 25, 50, 75][i % 4], "timeoutMs": 240000},
            setup={"inspectProcFd": True, "inspectThreadNames": True, "inspectChildProcesses": True, "forceShutdownAtEnd": True},
            assertions=["no_crash", "fd_count_returns_near_baseline", "thread_count_returns_near_baseline", "tn_child_process_count_returns_near_baseline"],
            leak_checks=["fd_count_returns_near_baseline", "thread_count_returns_near_baseline", "tn_child_process_count_returns_near_baseline", "stderr_watcher_thread_not_accumulating", "no_zombie_or_orphan_tn_process"],
        )


def build_stress_recovery_regression() -> None:
    ops = ["conv-invalid-input-guard", "tn-broken-pipe-recovery", "runner-background-freeze-guard", "engine-limit-recovery", "audio-track-release-regression", "next-request-after-native-error"]
    for i in range(COUNTS["stress-recovery-regression"]):
        op = ops[i % len(ops)]
        add_case(
            "stress-recovery-regression",
            i,
            title="known stability regression and recovery guard",
            operation=op,
            params={"chunkSize": [16, 25, 50, 100][i % 4], "pcmQueueCapacity": [1, 2, 4, 8][i % 4], "timeoutMs": 180000},
            setup={"regressionVariant": op, "recoverWithShortSpeak": True, "repeat": 1 + (i % 5)},
            assertions=["no_crash", "known_regression_not_reintroduced", "recovery_request_succeeds", "terminal_state_observed"],
            leak_checks=LEAK_CHECKS if i % 2 == 0 else ["fd_count_returns_near_baseline", "thread_count_returns_near_baseline"],
        )


def build_cases() -> None:
    build_smoke_api()
    build_engine_create_query()
    build_workpath_resource_load()
    build_lifecycle_state_machine()
    build_listener_callback_contract()
    build_request_queue_scheduler()
    build_streaming_config_buffering()
    build_playback_channel_audio_route()
    build_params_boundary_runtime()
    build_error_validation_recovery()
    build_longtext_tn_stability()
    build_memory_leak_soak()
    build_fd_thread_process_leak()
    build_stress_recovery_regression()


def validate() -> None:
    if len(CASES) != 1000:
        raise AssertionError(f"expected 1000 cases, got {len(CASES)}")
    counts = Counter(case["category"] for case in CASES)
    if dict(counts) != COUNTS:
        raise AssertionError(f"category mismatch: {counts} != {COUNTS}")
    ids = [case["id"] for case in CASES]
    if len(set(ids)) != len(ids):
        raise AssertionError("duplicate ids")
    removed = {"zh-core", "en-core", "mixed-zh-en", "tn-numeric-date-money-unit", "frontend-rules-technical", "polyphone-surname-proper", "symbols-unicode-failsoft"}
    if removed & set(counts):
        raise AssertionError(f"removed text-correctness categories still present: {removed & set(counts)}")
    semantic = [
        json.dumps(
            {
                "category": case["category"],
                "operation": case["operation"],
                "expected_status": case["expected_status"],
                "text": case["text"],
                "params": case["params"],
                "setup": case["setup"],
                "expectedErrorCode": case.get("expectedErrorCode"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        for case in CASES
    ]
    duplicates = [item for item, count in Counter(semantic).items() if count > 1]
    if duplicates:
        raise AssertionError(f"duplicate semantic cases: {duplicates[:3]}")
    golden_like = [case for case in CASES if any(key in case for key in ("is_golden", "expected_pinyin_sequence", "expected_phoneme_sequence", "golden_pronunciation"))]
    if golden_like:
        raise AssertionError(f"pronunciation/golden fields should be absent, found {golden_like[0]['id']}")


def write_outputs() -> None:
    with JSONL_PATH.open("w", encoding="utf-8") as f:
        for case in CASES:
            f.write(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n")
    summary = {
        "total": len(CASES),
        "target_counts": COUNTS,
        "category_counts": dict(Counter(case["category"] for case in CASES)),
        "status_counts": dict(Counter(case["expected_status"] for case in CASES)),
        "removed_text_correctness_categories": ["zh-core", "en-core", "mixed-zh-en", "tn-numeric-date-money-unit", "frontend-rules-technical", "polyphone-surname-proper", "symbols-unicode-failsoft"],
        "golden_case_count": 0,
        "pronunciation_correctness_cases_excluded": True,
        "no_duplicate_ids": True,
        "no_duplicate_semantic_cases": True,
        "jsonl": str(JSONL_PATH),
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Design doc is hand-maintained for industrial runtime-stability gates.
    # Do not overwrite ANDROID_V3_SDK_STABILITY_1000_CASE_DESIGN.md from this generator.


def main() -> None:
    build_cases()
    validate()
    write_outputs()
    print(f"wrote {len(CASES)} cases")
    print(JSONL_PATH)
    print(SUMMARY_PATH)
    print(REPORT_PATH)


if __name__ == "__main__":
    main()
