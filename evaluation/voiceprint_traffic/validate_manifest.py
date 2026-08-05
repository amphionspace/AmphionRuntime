#!/usr/bin/env python3
"""Validate a traffic-domain target-speaker evaluation manifest.

The validator intentionally uses only Python's standard library so collection and
acceptance hosts do not need a third-party JSON Schema runtime. The JSON Schema in
this directory remains the interchange contract; this program adds dataset-level
leakage and minimum-size checks that JSON Schema cannot express.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import re
import sys
import wave
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


SCHEMA_VERSION = "1.0"
SPLITS = {"pilot", "dev", "blind"}
DOMAINS = {"office", "traffic"}
PURPOSES = {"enrollment", "probe"}
SPEECH_MODES = {"separate", "sequential", "overlap"}
CONTENT_MODES = {"scripted", "semi_spontaneous", "spontaneous"}
LEVELS = {"none", "low", "medium", "high"}
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_TOP_LEVEL = {
    "schema_version",
    "recording_id",
    "source_recording_id",
    "split",
    "domain",
    "purpose",
    "audio_path",
    "audio_sha256",
    "session_id",
    "site_id",
    "target_speaker_id",
    "speaker_ids",
    "target_present",
    "speech_mode",
    "audio",
    "capture",
    "turns",
    "overlap_regions",
}

SUPPORTED_TOTAL_REQUIREMENTS = {
    f"{split}_{metric}"
    for split in SPLITS
    for metric in (
        "owners", "separate_positive", "separate_negative", "sequential", "overlap"
    )
}
SUPPORTED_PER_TARGET_REQUIREMENTS = {
    "separate_positive", "separate_negative", "sequential", "overlap"
}
REQUIRED_FORMAL_TOTALS = {
    "dev_owners",
    "dev_separate_positive",
    "dev_separate_negative",
    "blind_owners",
    "blind_separate_positive",
    "blind_separate_negative",
}


def _error(errors: list[str], line: int, message: str) -> None:
    errors.append(f"line {line}: {message}")


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and ID_PATTERN.fullmatch(value) is not None


def _valid_date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _relative_audio_path(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and path.suffix.lower() == ".wav"


def _non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validate_protocol(protocol: object) -> list[str]:
    """Validate a pre-registered study protocol without prescribing its numbers."""
    errors: list[str] = []
    if not isinstance(protocol, dict):
        return ["protocol: root must be an object"]
    if protocol.get("protocol_version") != "1.0":
        errors.append("protocol: protocol_version must be '1.0'")
    if protocol.get("status") != "frozen":
        errors.append("protocol: status must be 'frozen' before a formal gate")
    for field in ("study_id", "use_case", "decision_unit", "primary_domain"):
        if not isinstance(protocol.get(field), str) or not protocol[field].strip():
            errors.append(f"protocol: {field} must be a non-empty string")
    if protocol.get("primary_domain") != "traffic":
        errors.append("protocol: this dataset requires primary_domain='traffic'")
    metrics = protocol.get("primary_metrics")
    if not isinstance(metrics, list) or not metrics or any(
        not isinstance(metric, str) or not metric.strip() for metric in metrics
    ):
        errors.append("protocol: primary_metrics must be a non-empty string list")

    operating_point = protocol.get("operating_point")
    if not isinstance(operating_point, dict):
        errors.append("protocol: operating_point must be an object")
    else:
        for field in (
            "target_prior_source", "false_accept_cost", "false_reject_cost", "abstain_policy",
            "threshold_selection_split",
        ):
            if operating_point.get(field) is None or operating_point.get(field) == "":
                errors.append(f"protocol: operating_point.{field} is required")
        if operating_point.get("threshold_selection_split") != "dev":
            errors.append("protocol: threshold_selection_split must be 'dev'")

    confidence = protocol.get("confidence")
    if not isinstance(confidence, dict):
        errors.append("protocol: confidence must be an object")
    else:
        if confidence.get("method") not in {"cluster_bootstrap", "subject_bootstrap"}:
            errors.append("protocol: confidence.method must use speaker/session-aware bootstrap")
        level = confidence.get("level")
        if not isinstance(level, (int, float)) or isinstance(level, bool) or not 0.5 < level < 1:
            errors.append("protocol: confidence.level must be between 0.5 and 1")
        keys = confidence.get("cluster_keys")
        if not isinstance(keys, list) or "target_speaker_id" not in keys:
            errors.append("protocol: confidence.cluster_keys must include target_speaker_id")

    evidence = protocol.get("evidence_requirements")
    if not isinstance(evidence, dict):
        return errors + ["protocol: evidence_requirements must be an object"]
    if not isinstance(evidence.get("basis"), str) or not evidence["basis"].strip():
        errors.append("protocol: evidence_requirements.basis must document power-analysis basis")

    totals = evidence.get("totals")
    if not isinstance(totals, dict):
        errors.append("protocol: evidence_requirements.totals must be an object")
    else:
        missing_totals = sorted(REQUIRED_FORMAL_TOTALS - set(totals))
        if missing_totals:
            errors.append(
                "protocol: evidence_requirements.totals missing formal split requirements: "
                + ", ".join(missing_totals)
            )
        for key, value in totals.items():
            if key not in SUPPORTED_TOTAL_REQUIREMENTS:
                errors.append(f"protocol: unsupported total requirement {key!r}")
            if not _non_negative_int(value):
                errors.append(f"protocol: total requirement {key!r} must be a non-negative integer")
            if key in REQUIRED_FORMAL_TOTALS and not _positive_int(value):
                errors.append(f"protocol: formal total requirement {key!r} must be positive")

    per_target = evidence.get("per_target")
    if not isinstance(per_target, dict):
        errors.append("protocol: evidence_requirements.per_target must be an object")
    else:
        for split in ("dev", "blind"):
            requirements = per_target.get(split)
            if not isinstance(requirements, dict) or not {
                "separate_positive", "separate_negative"
            }.issubset(requirements):
                errors.append(
                    f"protocol: per_target.{split} must include separate_positive and "
                    "separate_negative"
                )
        for split, requirements in per_target.items():
            if split not in SPLITS or not isinstance(requirements, dict):
                errors.append(f"protocol: invalid per_target split {split!r}")
                continue
            for key, value in requirements.items():
                if key not in SUPPORTED_PER_TARGET_REQUIREMENTS:
                    errors.append(f"protocol: unsupported per-target requirement {key!r}")
                if not _non_negative_int(value):
                    errors.append(
                        f"protocol: per-target requirement {split}.{key} must be a non-negative integer"
                    )
                if key in {"separate_positive", "separate_negative"} and not _positive_int(value):
                    errors.append(
                        f"protocol: per-target requirement {split}.{key} must be positive"
                    )

    for field in (
        "min_enrollment_sessions_per_target",
        "min_probe_sessions_per_target",
        "min_probe_dates_per_target",
    ):
        values = evidence.get(field)
        if not isinstance(values, dict):
            errors.append(f"protocol: evidence_requirements.{field} must be an object")
            continue
        for split, value in values.items():
            if split not in SPLITS or not _non_negative_int(value):
                errors.append(f"protocol: invalid {field}.{split} requirement")
        for split in ("dev", "blind"):
            if split not in values:
                errors.append(f"protocol: {field}.{split} is required")
            elif not _positive_int(values[split]):
                errors.append(f"protocol: {field}.{split} must be positive")

    if not isinstance(evidence.get("require_unseen_blind_site"), bool):
        errors.append("protocol: evidence_requirements.require_unseen_blind_site must be boolean")
    if protocol.get("blind_usage") != "single_pass":
        errors.append("protocol: blind_usage must be 'single_pass'")
    return errors


def _validate_interval(
    interval: object,
    *,
    duration_ms: int,
    label: str,
    line: int,
    errors: list[str],
) -> tuple[int, int] | None:
    if not isinstance(interval, dict):
        _error(errors, line, f"{label} must be an object")
        return None
    start = interval.get("start_ms")
    end = interval.get("end_ms")
    if not isinstance(start, int) or not isinstance(end, int):
        _error(errors, line, f"{label} start_ms/end_ms must be integers")
        return None
    if start < 0 or end <= start or end > duration_ms:
        _error(errors, line, f"{label} interval [{start}, {end}] is outside 0..{duration_ms}")
        return None
    return start, end


def _region_has_two_speakers(
    region: tuple[int, int], turns: list[tuple[int, int, str]]
) -> bool:
    start, end = region
    boundaries = {start, end}
    for turn_start, turn_end, _ in turns:
        if turn_start < end and turn_end > start:
            boundaries.add(max(start, turn_start))
            boundaries.add(min(end, turn_end))
    ordered = sorted(boundaries)
    for left, right in zip(ordered, ordered[1:]):
        if right <= left:
            continue
        midpoint = (left + right) / 2
        active = {
            speaker for turn_start, turn_end, speaker in turns
            if turn_start <= midpoint < turn_end
        }
        if len(active) >= 2:
            return True
    return False


def validate_record(record: object, line: int, *, acceptance: bool = False) -> list[str]:
    errors: list[str] = []
    if not isinstance(record, dict):
        return [f"line {line}: each JSONL row must be an object"]

    missing = sorted(REQUIRED_TOP_LEVEL - set(record))
    if missing:
        _error(errors, line, f"missing required fields: {', '.join(missing)}")

    if record.get("schema_version") != SCHEMA_VERSION:
        _error(errors, line, f"schema_version must be {SCHEMA_VERSION!r}")
    for field in (
        "recording_id", "source_recording_id", "session_id", "site_id", "target_speaker_id"
    ):
        if not _valid_id(record.get(field)):
            _error(errors, line, f"{field} is not a valid pseudonymous ID")

    split = record.get("split")
    domain = record.get("domain")
    purpose = record.get("purpose")
    speech_mode = record.get("speech_mode")
    if split not in SPLITS:
        _error(errors, line, f"split must be one of {sorted(SPLITS)}")
    if domain not in DOMAINS:
        _error(errors, line, f"domain must be one of {sorted(DOMAINS)}")
    if purpose not in PURPOSES:
        _error(errors, line, f"purpose must be one of {sorted(PURPOSES)}")
    if speech_mode not in SPEECH_MODES:
        _error(errors, line, f"speech_mode must be one of {sorted(SPEECH_MODES)}")

    if not _relative_audio_path(record.get("audio_path")):
        _error(errors, line, "audio_path must be a relative .wav path without '..'")
    audio_hash = record.get("audio_sha256")
    if not isinstance(audio_hash, str) or SHA256_PATTERN.fullmatch(audio_hash) is None:
        _error(errors, line, "audio_sha256 must be 64 lowercase hexadecimal characters")

    if acceptance:
        if not _valid_date(record.get("recorded_date")):
            _error(errors, line, "acceptance manifest requires recorded_date in YYYY-MM-DD form")
        if not isinstance(record.get("language"), str) or not record["language"].strip():
            _error(errors, line, "acceptance manifest requires language")
        if "dialect" not in record:
            _error(errors, line, "acceptance manifest requires dialect (null is allowed)")
        if record.get("content_mode") not in CONTENT_MODES:
            _error(errors, line, f"acceptance manifest requires content_mode in {sorted(CONTENT_MODES)}")

    audio = record.get("audio")
    duration_ms = 0
    if not isinstance(audio, dict):
        _error(errors, line, "audio must be an object")
    else:
        if audio.get("sample_rate_hz") != 16000:
            _error(errors, line, "audio.sample_rate_hz must be 16000")
        if audio.get("channels") != 1:
            _error(errors, line, "audio.channels must be 1")
        if audio.get("sample_width_bits") != 16:
            _error(errors, line, "audio.sample_width_bits must be 16")
        value = audio.get("duration_ms")
        if not isinstance(value, int) or value <= 0:
            _error(errors, line, "audio.duration_ms must be a positive integer")
        else:
            duration_ms = value

    capture = record.get("capture")
    capture_required = {
        "device_model", "device_batch", "os_version", "sdk_version", "mic_placement",
        "distance_cm", "scene", "snr_db", "wind_level", "traffic_level",
    }
    if not isinstance(capture, dict):
        _error(errors, line, "capture must be an object")
    else:
        missing_capture = sorted(capture_required - set(capture))
        if missing_capture:
            _error(errors, line, f"capture missing: {', '.join(missing_capture)}")
        if capture.get("wind_level") not in LEVELS:
            _error(errors, line, f"capture.wind_level must be one of {sorted(LEVELS)}")
        if capture.get("traffic_level") not in LEVELS:
            _error(errors, line, f"capture.traffic_level must be one of {sorted(LEVELS)}")
        distance = capture.get("distance_cm")
        if not isinstance(distance, (int, float)) or isinstance(distance, bool) or distance < 0:
            _error(errors, line, "capture.distance_cm must be a non-negative number")
        snr = capture.get("snr_db")
        if snr is not None and (not isinstance(snr, (int, float)) or isinstance(snr, bool)):
            _error(errors, line, "capture.snr_db must be numeric or null")

    speaker_ids = record.get("speaker_ids")
    speakers: set[str] = set()
    if not isinstance(speaker_ids, list) or not speaker_ids:
        _error(errors, line, "speaker_ids must be a non-empty list")
    else:
        speakers = {speaker for speaker in speaker_ids if isinstance(speaker, str)}
        if len(speakers) != len(speaker_ids) or any(not _valid_id(item) for item in speaker_ids):
            _error(errors, line, "speaker_ids must contain unique valid IDs")

    target = record.get("target_speaker_id")
    target_present = record.get("target_present")
    if not isinstance(target_present, bool):
        _error(errors, line, "target_present must be boolean")
    elif isinstance(target, str) and target_present != (target in speakers):
        _error(errors, line, "target_present must exactly match target_speaker_id membership in speaker_ids")

    raw_turns = record.get("turns")
    turns: list[tuple[int, int, str]] = []
    turn_speakers: set[str] = set()
    if not isinstance(raw_turns, list) or not raw_turns:
        _error(errors, line, "turns must be a non-empty list")
    elif duration_ms:
        for index, turn in enumerate(raw_turns):
            interval = _validate_interval(
                turn, duration_ms=duration_ms, label=f"turns[{index}]", line=line, errors=errors
            )
            if not isinstance(turn, dict):
                continue
            speaker = turn.get("speaker_id")
            if speaker not in speakers:
                _error(errors, line, f"turns[{index}].speaker_id is not listed in speaker_ids")
            if not isinstance(turn.get("text"), str):
                _error(errors, line, f"turns[{index}].text must be a string")
            if interval and isinstance(speaker, str):
                turns.append((*interval, speaker))
                turn_speakers.add(speaker)
        if speakers and turn_speakers != speakers:
            _error(errors, line, "speaker_ids must exactly equal the speakers present in turns")

    raw_regions = record.get("overlap_regions")
    regions: list[tuple[int, int]] = []
    if not isinstance(raw_regions, list):
        _error(errors, line, "overlap_regions must be a list")
    elif duration_ms:
        for index, region in enumerate(raw_regions):
            interval = _validate_interval(
                region,
                duration_ms=duration_ms,
                label=f"overlap_regions[{index}]",
                line=line,
                errors=errors,
            )
            if interval:
                regions.append(interval)

    if speech_mode == "separate" and len(speakers) != 1:
        _error(errors, line, "speech_mode=separate requires exactly one speaking identity")
    if speech_mode in {"separate", "sequential"} and regions:
        _error(errors, line, f"speech_mode={speech_mode} requires empty overlap_regions")
    if speech_mode == "sequential" and len(speakers) < 2:
        _error(errors, line, "speech_mode=sequential requires at least two speaking identities")
    if speech_mode == "overlap":
        if len(speakers) < 2 or not regions:
            _error(errors, line, "speech_mode=overlap requires >=2 speakers and overlap_regions")
        for region in regions:
            if turns and not _region_has_two_speakers(region, turns):
                _error(errors, line, f"overlap region {region} has no verified two-speaker intersection")

    if purpose == "enrollment":
        if target_present is not True or speakers != {target}:
            _error(errors, line, "enrollment must contain target_speaker_id and no other speaker")
        if speech_mode != "separate":
            _error(errors, line, "enrollment must use speech_mode=separate")

    return errors


def _traffic_probe(record: dict[str, Any], split: str, mode: str | None = None) -> bool:
    return (
        record.get("split") == split
        and record.get("domain") == "traffic"
        and record.get("purpose") == "probe"
        and (mode is None or record.get("speech_mode") == mode)
    )


def summarize(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records = list(records)
    counts: collections.Counter[str] = collections.Counter()
    owners: dict[str, set[str]] = collections.defaultdict(set)
    for record in records:
        split = str(record.get("split"))
        if record.get("purpose") == "probe":
            owners[split].add(str(record.get("target_speaker_id")))
        if _traffic_probe(record, split, "separate"):
            polarity = "positive" if record.get("target_present") else "negative"
            counts[f"{split}_separate_{polarity}"] += 1
        if _traffic_probe(record, split, "overlap"):
            counts[f"{split}_overlap"] += 1
        if _traffic_probe(record, split, "sequential"):
            counts[f"{split}_sequential"] += 1
    result: dict[str, Any] = {"records": len(records)}
    for split in sorted(SPLITS):
        result[f"{split}_owners"] = len(owners[split])
    result.update(dict(sorted(counts.items())))
    return result


def validate_records(
    records: list[dict[str, Any]], *, acceptance: bool = False, protocol: object = None
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    protocol_errors = validate_protocol(protocol) if acceptance else []
    errors.extend(protocol_errors)
    evidence: dict[str, Any] = {}
    if acceptance and not protocol_errors and isinstance(protocol, dict):
        evidence = protocol["evidence_requirements"]
    for line, record in enumerate(records, 1):
        errors.extend(validate_record(record, line, acceptance=acceptance))

    recording_lines: dict[str, int] = {}
    hash_lines: dict[str, int] = {}
    source_splits: dict[str, set[str]] = collections.defaultdict(set)
    session_splits: dict[str, set[str]] = collections.defaultdict(set)
    speaker_splits: dict[str, set[str]] = collections.defaultdict(set)
    target_enrollment_sessions: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    target_probe_sessions: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    target_probe_dates: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    per_owner_counts: dict[tuple[str, str], collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    dev_sites: set[str] = set()
    blind_sites: set[str] = set()

    for line, record in enumerate(records, 1):
        recording_id = record.get("recording_id")
        if isinstance(recording_id, str):
            if recording_id in recording_lines:
                _error(errors, line, f"duplicate recording_id; first seen at line {recording_lines[recording_id]}")
            recording_lines[recording_id] = line
        audio_hash = record.get("audio_sha256")
        if isinstance(audio_hash, str):
            if audio_hash in hash_lines:
                _error(errors, line, f"duplicate audio_sha256; first seen at line {hash_lines[audio_hash]}")
            hash_lines[audio_hash] = line

        split = record.get("split")
        source = record.get("source_recording_id")
        session = record.get("session_id")
        if isinstance(split, str) and isinstance(source, str):
            source_splits[source].add(split)
        if isinstance(split, str) and isinstance(session, str):
            session_splits[session].add(split)
        if isinstance(split, str):
            for speaker in record.get("speaker_ids", []):
                if isinstance(speaker, str):
                    speaker_splits[speaker].add(split)

        target = record.get("target_speaker_id")
        if isinstance(split, str) and isinstance(target, str) and isinstance(session, str):
            key = (split, target)
            if record.get("purpose") == "enrollment":
                target_enrollment_sessions[key].add(session)
            elif record.get("purpose") == "probe":
                target_probe_sessions[key].add(session)
                date = record.get("recorded_date")
                if isinstance(date, str):
                    target_probe_dates[key].add(date)
                if record.get("domain") == "traffic":
                    if record.get("speech_mode") == "overlap":
                        per_owner_counts[key]["overlap"] += 1
                    elif record.get("speech_mode") == "separate":
                        polarity = "positive" if record.get("target_present") else "negative"
                        per_owner_counts[key][f"separate_{polarity}"] += 1

        if record.get("domain") == "traffic" and record.get("purpose") == "probe":
            site = record.get("site_id")
            if isinstance(site, str) and split == "dev":
                dev_sites.add(site)
            elif isinstance(site, str) and split == "blind":
                blind_sites.add(site)

    for source, splits in source_splits.items():
        if len(splits) > 1:
            errors.append(f"dataset: source_recording_id {source!r} crosses splits {sorted(splits)}")
    for session, splits in session_splits.items():
        if len(splits) > 1:
            errors.append(f"dataset: session_id {session!r} crosses splits {sorted(splits)}")
    for speaker, splits in speaker_splits.items():
        if len(splits) > 1:
            errors.append(f"dataset: speaker_id {speaker!r} crosses splits {sorted(splits)}")

    for key, probe_sessions in target_probe_sessions.items():
        enrollment_sessions = target_enrollment_sessions.get(key, set())
        minimum_enrollment_sessions = 1
        if evidence:
            minimum_enrollment_sessions = evidence["min_enrollment_sessions_per_target"].get(
                key[0], 0
            )
        if len(enrollment_sessions) < minimum_enrollment_sessions:
            errors.append(
                f"dataset: target {key[1]!r} in split {key[0]!r} has "
                f"{len(enrollment_sessions)} enrollment sessions; "
                f"require >= {minimum_enrollment_sessions}"
            )
        overlap = enrollment_sessions & probe_sessions
        if overlap:
            errors.append(
                f"dataset: target {key[1]!r} reuses enrollment sessions as probe: {sorted(overlap)}"
            )
        if evidence:
            minimum_probe_sessions = evidence["min_probe_sessions_per_target"].get(key[0], 0)
            if len(probe_sessions) < minimum_probe_sessions:
                errors.append(
                    f"dataset: target {key[1]!r} in split {key[0]!r} has "
                    f"probe_sessions={len(probe_sessions)}; require >= {minimum_probe_sessions}"
                )
            minimum_probe_dates = evidence["min_probe_dates_per_target"].get(key[0], 0)
            actual_dates = len(target_probe_dates.get(key, set()))
            if actual_dates < minimum_probe_dates:
                errors.append(
                    f"dataset: target {key[1]!r} in split {key[0]!r} has "
                    f"probe_dates={actual_dates}; require >= {minimum_probe_dates}"
                )

    if evidence:
        for key, counts in per_owner_counts.items():
            split, target = key
            minimums = evidence["per_target"].get(split)
            if minimums is None:
                continue
            for category, minimum in minimums.items():
                actual = counts[category]
                if actual < minimum:
                    errors.append(
                        f"dataset: target {target!r} in split {split!r} has "
                        f"{category}={actual}; require >= {minimum}"
                    )

    summary = summarize(records)
    if evidence:
        for metric, minimum in evidence["totals"].items():
            actual = int(summary.get(metric, 0))
            if actual < minimum:
                errors.append(f"dataset: {metric}={actual}, require >= {minimum}")
        if evidence["require_unseen_blind_site"] and not (blind_sites - dev_sites):
            errors.append("dataset: blind traffic probes require at least one site absent from dev")
    elif records:
        warnings.append(
            "formal pre-registered evidence requirements were not checked; "
            "pass --acceptance with --protocol"
        )

    return errors, warnings, summary


def load_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, 1):
            if not raw_line.strip():
                continue
            try:
                value = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {line_number}: invalid JSON: {exc.msg}")
                continue
            if not isinstance(value, dict):
                errors.append(f"line {line_number}: each JSONL row must be an object")
                continue
            records.append(value)
    return records, errors


def check_audio_files(records: list[dict[str, Any]], dataset_root: Path) -> list[str]:
    errors: list[str] = []
    root = dataset_root.resolve()
    for line, record in enumerate(records, 1):
        relative = record.get("audio_path")
        if not _relative_audio_path(relative):
            continue
        path = (root / str(relative)).resolve()
        if root not in path.parents:
            _error(errors, line, "audio_path resolves outside dataset root")
            continue
        if not path.is_file():
            _error(errors, line, f"audio file does not exist: {relative}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != record.get("audio_sha256"):
            _error(errors, line, f"audio SHA-256 mismatch: {relative}")
        try:
            with wave.open(str(path), "rb") as wav:
                sample_rate = wav.getframerate()
                channels = wav.getnchannels()
                sample_width_bits = wav.getsampwidth() * 8
                duration_ms = round(wav.getnframes() * 1000 / sample_rate)
        except (wave.Error, EOFError) as exc:
            _error(errors, line, f"invalid PCM WAV {relative}: {exc}")
            continue
        expected = record.get("audio", {})
        if sample_rate != expected.get("sample_rate_hz"):
            _error(errors, line, f"WAV sample rate mismatch: {relative}")
        if channels != expected.get("channels"):
            _error(errors, line, f"WAV channel mismatch: {relative}")
        if sample_width_bits != expected.get("sample_width_bits"):
            _error(errors, line, f"WAV sample width mismatch: {relative}")
        expected_duration = expected.get("duration_ms")
        if isinstance(expected_duration, int) and abs(duration_ms - expected_duration) > 20:
            _error(
                errors,
                line,
                f"WAV duration mismatch: manifest={expected_duration} ms actual={duration_ms} ms",
            )
    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--dataset-root", type=Path)
    parser.add_argument("--check-files", action="store_true")
    parser.add_argument("--acceptance", action="store_true")
    parser.add_argument("--protocol", type=Path)
    args = parser.parse_args(argv)
    if args.check_files and args.dataset_root is None:
        parser.error("--check-files requires --dataset-root")
    if args.acceptance and args.protocol is None:
        parser.error("--acceptance requires a frozen --protocol")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    records, errors = load_jsonl(args.manifest)
    protocol: object = None
    if args.protocol is not None:
        try:
            protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"protocol: cannot load {args.protocol}: {exc}")
    validation_errors, warnings, summary = validate_records(
        records, acceptance=args.acceptance, protocol=protocol
    )
    errors.extend(validation_errors)
    if args.check_files:
        errors.extend(check_audio_files(records, args.dataset_root))

    print(json.dumps({"summary": summary, "warnings": warnings}, ensure_ascii=False, indent=2))
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        print(f"FAIL: {len(errors)} error(s)", file=sys.stderr)
        return 1
    print("PASS: manifest is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
