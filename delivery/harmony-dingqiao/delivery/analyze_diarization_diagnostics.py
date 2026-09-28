#!/usr/bin/env python3
"""Locate the first observable failure in an offline diarization run.

The analyzer consumes the SDK's redacted ``events.ndjson`` journal.  It keeps
the stages separate: an internal community result is not treated as proof
that the SDK callback or the caller display was correct.  Presence of a stage only proves observation, not correctness. Missing
evidence stays ``UNVERIFIED``; observed but unscored stages stay ``INCONCLUSIVE``.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable


STAGES = [
    "input",
    "asr",
    "segmentation",
    "embedding",
    "clustering",
    "identity_freeze",
    "sdk_alignment",
    "caller_display",
]


def _sequence(event: dict[str, Any], fallback: int) -> int:
    value = event.get("sequence", fallback)
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSON at {path}:{line_number}: {error}") from error
        if not isinstance(value, dict) or not isinstance(value.get("event"), str):
            raise ValueError(f"event at {path}:{line_number} must contain an event name")
        fields = value.get("fields", {})
        if fields is None:
            value["fields"] = {}
        elif not isinstance(fields, dict):
            raise ValueError(f"fields at {path}:{line_number} must be an object")
        value["_line"] = line_number
        value["_sequence"] = _sequence(value, line_number)
        events.append(value)
    return sorted(events, key=lambda item: (item["_sequence"], item["_line"]))


def _fields(event: dict[str, Any]) -> dict[str, Any]:
    return event.get("fields", {})


def _normalise_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give programmatic test fixtures the same metadata as load_events()."""
    normalised: list[dict[str, Any]] = []
    for index, value in enumerate(events, 1):
        event = dict(value)
        event.setdefault("_sequence", _sequence(event, index))
        event.setdefault("_line", index)
        event.setdefault("fields", {})
        if not isinstance(event["fields"], dict):
            raise ValueError(f"event {index} fields must be an object")
        normalised.append(event)
    return sorted(normalised, key=lambda item: (item["_sequence"], item["_line"]))


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive(value: Any) -> bool:
    number = _number(value)
    return number is not None and number > 0


def _result(status: str, reason: str, event: dict[str, Any] | None = None,
            *, evidence: Iterable[str] = ()) -> dict[str, Any]:
    output: dict[str, Any] = {"status": status, "reason": reason}
    if event is not None:
        output["firstSequence"] = event["_sequence"]
        output["firstEvent"] = event["event"]
    output["evidence"] = list(evidence)
    return output


def _first(events: list[dict[str, Any]], names: set[str],
           predicate: Any = None) -> dict[str, Any] | None:
    for event in events:
        if event["event"] not in names:
            continue
        if predicate is None or predicate(event):
            return event
    return None


def _stage_results(events: list[dict[str, Any]], caller: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    audio = _first(
        events,
        {"AUDIO_FIRST_FRAME", "AUDIO_PROGRESS", "DIARIZATION_AUDIO_APPENDED"},
        lambda event: any(_positive(_fields(event).get(key)) for key in (
            "audioBytesWritten", "frames", "audioEndSample", "bytes")),
    )
    input_status = "PASS" if audio else "UNVERIFIED"

    asr = _first(
        events,
        {"DIARIZATION_ASR_ALIGNMENT", "DIARIZATION_ASR_PROCESSED", "CALLBACK_RESULT"},
        lambda event: event["event"] != "CALLBACK_RESULT" or
        _positive(_fields(event).get("textChars")) or
        _fields(event).get("isFinal") is True or _fields(event).get("isLast") is True,
    )
    asr_status = "INCONCLUSIVE" if asr else "UNVERIFIED"

    window = _first(events, {"DIARIZATION_COMMUNITY_WINDOW"})
    segmentation_status = "INCONCLUSIVE" if window else "UNVERIFIED"

    samples = _first(events, {"DIARIZATION_COMMUNITY_SAMPLES"})
    window_embeddings = _first(
        events, {"DIARIZATION_COMMUNITY_WINDOW"},
        lambda event: isinstance(_fields(event).get("embeddings"), list) and
        bool(_fields(event).get("embeddings")),
    )
    embedding = samples or window_embeddings
    embedding_status = "INCONCLUSIVE" if embedding else "UNVERIFIED"

    cluster = _first(events, {"DIARIZATION_COMMUNITY_PREVIEW", "DIARIZATION_COMMUNITY_COMMIT"})
    clustering_status = "INCONCLUSIVE" if cluster else "UNVERIFIED"

    commit = _first(events, {"DIARIZATION_COMMUNITY_COMMIT"})
    commit_has_identity = bool(commit and (
        _fields(commit).get("clusterToFrozenId") or
        _fields(commit).get("registryAfter") or
        _fields(commit).get("firstAppearanceTimes")
    ))
    identity_status = "INCONCLUSIVE" if commit_has_identity else "UNVERIFIED"

    public = _first(events, {"DIARIZATION_PUBLIC_RESULT"})
    sdk_status = "INCONCLUSIVE" if public else "UNVERIFIED"

    if caller is None:
        caller_result = _result("UNVERIFIED", "没有提供调用方最终 payload；SDK 诊断事件不能代替用户展示证据")
    else:
        turns = caller.get("speakerTurns")
        text = caller.get("text")
        if isinstance(turns, list) and turns and (text is None or isinstance(text, str)):
            caller_result = _result("INCONCLUSIVE", "调用方 payload 已采集；尚未核对原句、时间轴、推断标记和实际展示", evidence=["caller.speakerTurns"])
        else:
            caller_result = _result("FAIL", "调用方 payload 缺少可读 speakerTurns", evidence=["caller"])

    return {
        "input": _result(input_status, "录音帧已进入 SDK" if audio else "没有正的音频输入证据", audio, evidence=["audio counters"] if audio else []),
        "asr": _result(asr_status, "存在 ASR 处理或带文本回调" if asr else "音频进入后没有 ASR 处理/文本证据", asr, evidence=["ASR alignment/processed"] if asr else []),
        "segmentation": _result(segmentation_status, "存在 Community window" if window else "没有 Community window", window, evidence=["DIARIZATION_COMMUNITY_WINDOW"] if window else []),
        "embedding": _result(embedding_status, "存在样本或 embedding" if embedding else "窗口存在但没有样本/embedding 证据", embedding, evidence=["community samples/window embeddings"] if embedding else []),
        "clustering": _result(clustering_status, "存在 preview/commit 聚类结果" if cluster else "没有聚类结果", cluster, evidence=["community preview/commit"] if cluster else []),
        "identity_freeze": _result(identity_status, "commit 包含身份注册表" if commit_has_identity else "最终公开结果缺少身份冻结证据", commit, evidence=["clusterToFrozenId/registryAfter"] if commit_has_identity else []),
        "sdk_alignment": _result(sdk_status, "存在公开角色结果" if public else "没有公开角色结果", public, evidence=["DIARIZATION_PUBLIC_RESULT"] if public else []),
        "caller_display": caller_result,
    }


def _lifecycle(events: list[dict[str, Any]]) -> dict[str, Any]:
    finish = _first(events, {"FINISH_REQUESTED", "AUTO_FINISH_REQUESTED"})
    cancel = _first(events, {"CANCEL_REQUESTED"})
    last_events = [
        event for event in events
        if event["event"] == "CALLBACK_RESULT" and _fields(event).get("isLast") is True
    ]
    complete_events = [event for event in events if event["event"] == "CALLBACK_COMPLETE"]
    finals = [event for event in events if event["event"] == "CALLBACK_RESULT" and
              (_fields(event).get("isFinal") is True or _fields(event).get("isLast") is True)]
    errors = [event for event in events if event["event"] == "CALLBACK_ERROR"]
    if cancel is not None:
        late = [event for event in finals + complete_events if event["_sequence"] > cancel["_sequence"]]
        invalid = bool(late or last_events or complete_events or errors)
        return {
            "status": "FAIL" if invalid else "PASS",
            "reason": "cancel 前后存在非法 final/last/complete/error" if invalid else "cancel 后没有新增 final/complete",
            "lastCount": len(last_events),
            "completeCount": len(complete_events),
        }
    if finish is None and not (last_events or complete_events or errors):
        return {"status": "UNVERIFIED", "reason": "没有 finish 或明确自动结束事件", "lastCount": len(last_events), "completeCount": len(complete_events)}
    before_finish = [event for event in last_events if finish is None or event["_sequence"] < finish["_sequence"]]
    valid = len(last_events) == 1 and len(complete_events) == 1 and not before_finish and not errors
    if valid:
        valid = last_events[0]["_sequence"] < complete_events[0]["_sequence"] and not any(
            event["_sequence"] > last_events[0]["_sequence"] for event in finals if event is not last_events[0])
    return {
        "status": "PASS" if valid else "FAIL",
        "reason": "唯一 last 后唯一 complete" if valid else "last/complete 数量或顺序违反契约",
        "lastCount": len(last_events),
        "completeCount": len(complete_events),
        "isLastBeforeFinish": bool(before_finish),
    }


def _queue(events: list[dict[str, Any]], pending_limit: int) -> dict[str, Any]:
    samples: list[dict[str, float]] = []
    for event in events:
        if event["event"] != "DIARIZATION_QUEUE":
            continue
        fields = _fields(event)
        pending = _number(fields.get("pendingJobs"))
        native = _number(fields.get("nativeCallsInFlight"))
        delay = _number(fields.get("audioDelayMs"))
        if pending is not None:
            samples.append({
                "sequence": event["_sequence"],
                "pendingJobs": pending,
                "nativeCallsInFlight": native if native is not None else -1,
                "audioDelayMs": delay if delay is not None else -1,
            })
    if not samples:
        return {"status": "UNVERIFIED", "reason": "没有 DIARIZATION_QUEUE 样本", "sampleCount": 0}
    max_pending = max(item["pendingJobs"] for item in samples)
    first_pending = samples[0]["pendingJobs"]
    last_pending = samples[-1]["pendingJobs"]
    # A bounded job queue can hide an increasing PCM backlog. Endpoints and
    # short runs do not establish sustained realtime or a memory bound.
    status = "FAIL" if max_pending > pending_limit else "INCONCLUSIVE"
    return {
        "status": status,
        "reason": "队列超过上限" if status == "FAIL" else "已采集队列；须结合时间跨度、PCM 延迟和内存趋势判定实时性",
        "sampleCount": len(samples),
        "maxPendingJobs": max_pending,
        "maxNativeCallsInFlight": max(item["nativeCallsInFlight"] for item in samples),
        "maxAudioDelayMs": max(item["audioDelayMs"] for item in samples),
        "firstPendingJobs": first_pending,
        "lastPendingJobs": last_pending,
        "pendingLimit": pending_limit,
    }


def _identity(evaluation: dict[str, Any] | None,
              observed_speaker_counts: list[int] | None = None,
              expected_speaker_count: int | None = None) -> dict[str, Any]:
    failures: list[str] = []
    if expected_speaker_count is not None and observed_speaker_counts:
        for index, observed in enumerate(observed_speaker_counts):
            if observed != expected_speaker_count:
                failures.append(
                    f"session-{index + 1}:speakerCount={observed},expected={expected_speaker_count}"
                )
    if evaluation is None:
        return {
            "status": "FAIL" if failures else "UNVERIFIED",
            "reason": "公开角色人数与外部标注不一致" if failures else "没有提供公开集或标注评测 JSON",
            "failures": failures,
            "observedSpeakerCounts": observed_speaker_counts or [],
            "expectedSpeakerCount": expected_speaker_count,
        }
    metrics = evaluation.get("metrics") if isinstance(evaluation.get("metrics"), dict) else evaluation
    results = evaluation.get("results", {"recording": evaluation})
    if isinstance(results, dict):
        for name, item in results.items():
            if not isinstance(item, dict):
                continue
            if item.get("speakerCountError", 0) != 0:
                failures.append(f"{name}:speakerCountError={item.get('speakerCountError')}")
            if item.get("minoritySpeakerRecall") == 0:
                failures.append(f"{name}:minoritySpeakerRecall=0")
            stability = item.get("identityStability", {})
            if isinstance(stability, dict) and stability.get("sameSpeakerIdSwitchCount", 0) > 0:
                failures.append(f"{name}:identitySwitches={stability.get('sameSpeakerIdSwitchCount')}")
    return {
        "status": "FAIL" if failures else "INCONCLUSIVE",
        "reason": "存在已证实的身份缺失/切换" if failures else "没有显式项目门槛，不能仅凭评测 JSON 宣称通过",
        "failures": failures,
        "metrics": metrics,
        "observedSpeakerCounts": observed_speaker_counts or [],
        "expectedSpeakerCount": expected_speaker_count,
    }


def _merge_status(results: list[dict[str, Any]]) -> str:
    statuses = {item["status"] for item in results}
    if "FAIL" in statuses:
        return "FAIL"
    if "UNVERIFIED" in statuses:
        return "UNVERIFIED"
    if "INCONCLUSIVE" in statuses:
        return "INCONCLUSIVE"
    return "PASS"


def _merge_stage_results(per_session: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for stage in STAGES:
        values = [summary["stages"][stage] for summary in per_session.values()]
        status = _merge_status(values)
        first = next((value for value in values if value["status"] == status), values[0])
        merged[stage] = {
            "status": status,
            "reason": f"{len(values)} 个 session 聚合：{first.get('reason', '')}",
            "sessions": {session_id: summary["stages"][stage] for session_id, summary in per_session.items()},
        }
        if "firstSequence" in first:
            merged[stage]["firstSequence"] = first["firstSequence"]
        if "firstEvent" in first:
            merged[stage]["firstEvent"] = first["firstEvent"]
    return merged


def _summarize_session(events: list[dict[str, Any]], caller: dict[str, Any] | None,
                       pending_limit: int) -> dict[str, Any]:
    stage_results = _stage_results(events, caller)
    first_failure = next((stage for stage in STAGES if stage_results[stage]["status"] == "FAIL"), None)
    first_unverified = next((stage for stage in STAGES if stage_results[stage]["status"] == "UNVERIFIED"), None)
    return {
        "eventCount": len(events),
        "sequence": {"first": events[0]["_sequence"], "last": events[-1]["_sequence"]},
        "firstDivergenceStage": first_failure,
        "firstUnverifiedStage": first_unverified,
        "stages": stage_results,
        "lifecycle": _lifecycle(events),
        "queue": _queue(events, pending_limit),
    }


def summarize(events: list[dict[str, Any]], *, caller: dict[str, Any] | None = None,
              evaluation: dict[str, Any] | None = None, pending_limit: int = 2,
              expected_speaker_count: int | None = None) -> dict[str, Any]:
    events = _normalise_events(events)
    if not events:
        raise ValueError("diagnostic journal is empty")
    session_ids = sorted({str(event.get("sessionId")) for event in events if event.get("sessionId")})
    if not session_ids:
        session_ids = ["_all"]
    per_session = {
        session_id: _summarize_session(
            [event for event in events if session_id == "_all" or event.get("sessionId") == session_id],
            caller,
            pending_limit,
        )
        for session_id in session_ids
    }
    stage_results = _merge_stage_results(per_session)
    first_failure = next((stage for stage in STAGES if stage_results[stage]["status"] == "FAIL"), None)
    first_unverified = next((stage for stage in STAGES if stage_results[stage]["status"] == "UNVERIFIED"), None)
    lifecycle_values = [summary["lifecycle"] for summary in per_session.values()]
    queue_values = [summary["queue"] for summary in per_session.values()]
    lifecycle = dict(lifecycle_values[0])
    lifecycle["status"] = _merge_status(lifecycle_values)
    lifecycle["sessionCount"] = len(lifecycle_values)
    queue = dict(queue_values[0])
    queue["status"] = _merge_status(queue_values)
    queue["sessionCount"] = len(queue_values)
    if all("maxPendingJobs" in value for value in queue_values):
        queue["maxPendingJobs"] = max(value["maxPendingJobs"] for value in queue_values)
    if all("sampleCount" in value for value in queue_values):
        queue["sampleCount"] = sum(value["sampleCount"] for value in queue_values)
    observed_speaker_counts = [
        int(_fields(event)["speakerCount"])
        for event in events
        if event["event"] == "DIARIZATION_PUBLIC_RESULT" and
        _fields(event).get("isSessionFinal") is True and
        isinstance(_fields(event).get("speakerCount"), int)
    ]
    identity_accuracy = _identity(
        evaluation,
        observed_speaker_counts=observed_speaker_counts,
        expected_speaker_count=expected_speaker_count,
    )
    first_observed_failure = first_failure
    if first_observed_failure is None and lifecycle["status"] == "FAIL":
        first_observed_failure = "lifecycle"
    if first_observed_failure is None and queue["status"] == "FAIL":
        first_observed_failure = "realtime_queue"
    if first_observed_failure is None and identity_accuracy["status"] == "FAIL":
        first_observed_failure = "identity_accuracy"
    all_statuses = [stage["status"] for stage in stage_results.values()]
    all_statuses.extend([lifecycle["status"], queue["status"], identity_accuracy["status"]])
    overall_status = "FAIL" if "FAIL" in all_statuses else (
        "INCONCLUSIVE" if any(status in {"UNVERIFIED", "INCONCLUSIVE"} for status in all_statuses)
        else "PASS"
    )
    return {
        "eventCount": len(events),
        "sequence": {"first": events[0]["_sequence"], "last": events[-1]["_sequence"]},
        "firstDivergenceStage": first_failure,
        "firstObservedFailure": first_observed_failure,
        "firstUnverifiedStage": first_unverified,
        "overallStatus": overall_status,
        "stages": stage_results,
        "lifecycle": lifecycle,
        "queue": queue,
        "identityAccuracy": identity_accuracy,
        "sessions": per_session,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--evaluation", type=Path)
    parser.add_argument("--caller", type=Path, help="JSON payload captured by the real caller")
    parser.add_argument("--pending-limit", type=int, default=2)
    parser.add_argument("--expected-speaker-count", type=int,
                        help="External reference count for offline quality diagnosis; never sent to the SDK.")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.pending_limit < 0:
        raise SystemExit("--pending-limit must be non-negative")
    caller = json.loads(args.caller.read_text(encoding="utf-8")) if args.caller else None
    evaluation = json.loads(args.evaluation.read_text(encoding="utf-8")) if args.evaluation else None
    result = summarize(load_events(args.events), caller=caller, evaluation=evaluation,
                       pending_limit=args.pending_limit,
                       expected_speaker_count=args.expected_speaker_count)
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return {"PASS": 0, "FAIL": 1, "INCONCLUSIVE": 2}[result["overallStatus"]]


if __name__ == "__main__":
    raise SystemExit(main())
