#!/usr/bin/env python3
"""Evaluate a Harmony device-stress speaker timeline against an RTTM reference."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decode_turns(report: dict[str, Any], cycle_index: int) -> list[dict[str, Any]]:
    cycles = report.get("cycles")
    if not isinstance(cycles, list) or cycle_index < 0 or cycle_index >= len(cycles):
        raise ValueError("report cycle index is out of range")
    encoded = cycles[cycle_index].get("speakerTurnsHex", "")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("report does not contain speakerTurnsHex")
    turns = json.loads(bytes.fromhex(encoded).decode("utf-16-be"))
    if not isinstance(turns, list):
        raise ValueError("speakerTurnsHex does not contain an array")
    return turns


def _load_reference(path: Path, offset_seconds: float,
                    duration_seconds: float) -> list[tuple[float, float, str]]:
    output: list[tuple[float, float, str]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 8 or fields[0] != "SPEAKER":
            raise ValueError(f"invalid RTTM at line {line_number}")
        start = float(fields[3]) - offset_seconds
        end = start + float(fields[4])
        clipped_start = max(0.0, start)
        clipped_end = min(duration_seconds, end)
        if clipped_end > clipped_start:
            output.append((clipped_start, clipped_end, fields[7]))
    return output


def _best_mapping(overlap: list[list[int]], reference_ids: list[str],
                  system_ids: list[int]) -> dict[int, str]:
    size = max(len(reference_ids), len(system_ids))
    if size > 8:
        raise ValueError("at most eight speakers are supported by this evaluator")
    best_score = -1
    best: tuple[int, ...] = tuple()
    for assignment in itertools.permutations(range(size)):
        score = sum(
            overlap[reference_index][system_index]
            for system_index, reference_index in enumerate(assignment[:len(system_ids)])
            if reference_index < len(reference_ids)
        )
        if score > best_score:
            best_score = score
            best = assignment
    return {
        system_ids[system_index]: reference_ids[reference_index]
        for system_index, reference_index in enumerate(best[:len(system_ids)])
        if reference_index < len(reference_ids)
    }


def evaluate(turns: list[dict[str, Any]],
             reference: list[tuple[float, float, str]],
             duration_seconds: float, frame_ms: int = 10,
             collar_seconds: float = 0.25) -> dict[str, Any]:
    frame_seconds = frame_ms / 1000.0
    frame_count = int(duration_seconds / frame_seconds)
    reference_ids = sorted({speaker for _, _, speaker in reference})
    system_ids = sorted({
        int(speaker)
        for turn in turns
        for speaker in [turn.get("speakerIndex", -1),
                        *turn.get("secondarySpeakerIndexes", [])]
        if isinstance(speaker, int) and speaker >= 0
    })
    reference_frames: list[set[str]] = [set() for _ in range(frame_count)]
    system_frames: list[set[int]] = [set() for _ in range(frame_count)]
    overlap_flags = [False] * frame_count
    secondary_evidence_flags = [False] * frame_count
    identified_overlap_flags = [False] * frame_count

    def frame_bounds(start: float, end: float) -> range:
        first = max(0, int(start / frame_seconds))
        last = min(frame_count, int((end + frame_seconds - 1e-12) / frame_seconds))
        return range(first, last)

    for start, end, speaker in reference:
        for frame in frame_bounds(start, end):
            center = (frame + 0.5) * frame_seconds
            if start <= center < end:
                reference_frames[frame].add(speaker)
    unknown_frames: set[int] = set()
    for turn in turns:
        start = float(turn["beginTime"]) / 1000.0
        end = float(turn["endTime"]) / 1000.0
        primary = int(turn.get("speakerIndex", -1))
        raw_secondary = turn.get("secondarySpeakerIndexes", [])
        secondary = [int(value) for value in raw_secondary
                     if isinstance(value, int) and value >= 0]
        for frame in frame_bounds(start, end):
            center = (frame + 0.5) * frame_seconds
            if not start <= center < end:
                continue
            if primary >= 0:
                system_frames[frame].add(primary)
            else:
                unknown_frames.add(frame)
            system_frames[frame].update(secondary)
            overlap_flags[frame] = overlap_flags[frame] or bool(turn.get("overlap", False))
            secondary_evidence_flags[frame] = (
                secondary_evidence_flags[frame] or bool(raw_secondary))
            identified_overlap_flags[frame] = identified_overlap_flags[frame] or bool(secondary)

    overlap_matrix = [[0 for _ in system_ids] for _ in reference_ids]
    for frame in range(frame_count):
        for reference_speaker in reference_frames[frame]:
            for system_speaker in system_frames[frame]:
                overlap_matrix[reference_ids.index(reference_speaker)][
                    system_ids.index(system_speaker)] += 1
    mapping = _best_mapping(overlap_matrix, reference_ids, system_ids)

    missed = false_alarm = confusion = reference_time = 0
    correct_single = single_reference = 0
    reference_overlap = secondary_evidence = identified_overlap = 0
    system_overlap = overlap_intersection = 0
    secondary_evidence_intersection = identified_overlap_intersection = 0
    per_reference_total = {speaker: 0 for speaker in reference_ids}
    per_reference_correct = {speaker: 0 for speaker in reference_ids}
    for frame in range(frame_count):
        ref = reference_frames[frame]
        mapped = {mapping[speaker] for speaker in system_frames[frame] if speaker in mapping}
        reference_time += len(ref)
        correct = len(ref & mapped)
        missed += max(0, len(ref) - len(system_frames[frame]))
        false_alarm += max(0, len(system_frames[frame]) - len(ref))
        confusion += min(len(ref), len(system_frames[frame])) - correct
        for speaker in ref:
            per_reference_total[speaker] += 1
            if speaker in mapped:
                per_reference_correct[speaker] += 1
        if len(ref) == 1:
            single_reference += 1
            if correct == 1:
                correct_single += 1
        if len(ref) >= 2:
            reference_overlap += 1
            if overlap_flags[frame]:
                overlap_intersection += 1
            if secondary_evidence_flags[frame]:
                secondary_evidence_intersection += 1
            if identified_overlap_flags[frame]:
                identified_overlap_intersection += 1
        if overlap_flags[frame]:
            system_overlap += 1
        if secondary_evidence_flags[frame]:
            secondary_evidence += 1
        if identified_overlap_flags[frame]:
            identified_overlap += 1

    boundary_centers = [value for start, end, _ in reference for value in (start, end)]
    collar_frames: list[int] = []
    for frame in range(frame_count):
        center = (frame + 0.5) * frame_seconds
        if len(reference_frames[frame]) > 1:
            continue
        if any(abs(center - boundary) < collar_seconds for boundary in boundary_centers):
            continue
        collar_frames.append(frame)
    collar_ref = collar_miss = collar_fa = collar_confusion = 0
    for frame in collar_frames:
        ref = reference_frames[frame]
        mapped = {mapping[speaker] for speaker in system_frames[frame] if speaker in mapping}
        collar_ref += len(ref)
        correct = len(ref & mapped)
        collar_miss += max(0, len(ref) - len(system_frames[frame]))
        collar_fa += max(0, len(system_frames[frame]) - len(ref))
        collar_confusion += min(len(ref), len(system_frames[frame])) - correct

    def seconds(frames: int) -> float:
        return round(frames * frame_seconds, 3)

    def ratio(numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 6) if denominator else 0.0

    recalls = {
        speaker: ratio(per_reference_correct[speaker], per_reference_total[speaker])
        for speaker in reference_ids
    }
    return {
        "durationSeconds": duration_seconds,
        "frameMs": frame_ms,
        "referenceSpeakerCount": len(reference_ids),
        "systemSpeakerCount": len(system_ids),
        "speakerCountError": len(system_ids) - len(reference_ids),
        "speakerMapping": {str(speaker): reference for speaker, reference in mapping.items()},
        "der": ratio(missed + false_alarm + confusion, reference_time),
        "missedSpeechSeconds": seconds(missed),
        "falseAlarmSeconds": seconds(false_alarm),
        "speakerConfusionSeconds": seconds(confusion),
        "referenceSpeakerSeconds": seconds(reference_time),
        "classicDer250msNoOverlap": ratio(
            collar_miss + collar_fa + collar_confusion, collar_ref),
        "singleSpeakerAttributionAccuracy": ratio(correct_single, single_reference),
        "macroSpeakerRecall": round(sum(recalls.values()) / len(recalls), 6) if recalls else 0.0,
        "minoritySpeakerRecall": min(recalls.values()) if recalls else 0.0,
        "perSpeakerRecall": recalls,
        "referenceOverlapSeconds": seconds(reference_overlap),
        "detectedOverlapSeconds": seconds(system_overlap),
        "overlapDetectionRecall": ratio(overlap_intersection, reference_overlap),
        "overlapDetectionPrecision": ratio(overlap_intersection, system_overlap),
        "secondaryEvidenceSeconds": seconds(secondary_evidence),
        "secondaryEvidenceRecall": ratio(secondary_evidence_intersection, reference_overlap),
        "identifiedSecondarySeconds": seconds(identified_overlap),
        "identifiedSecondaryRecall": ratio(identified_overlap_intersection, reference_overlap),
        "unknownTurnSeconds": seconds(len(unknown_frames)),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--reference-rttm", type=Path, required=True)
    parser.add_argument("--reference-offset-seconds", type=float, default=0.0)
    parser.add_argument("--duration-seconds", type=float, required=True)
    parser.add_argument("--frame-ms", type=int, default=10)
    parser.add_argument("--cycle-index", type=int, default=0)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.duration_seconds <= 0 or args.frame_ms <= 0:
        raise SystemExit("duration and frame size must be positive")
    report = json.loads(args.report.read_text(encoding="utf-8"))
    turns = _decode_turns(report, args.cycle_index)
    reference = _load_reference(
        args.reference_rttm, args.reference_offset_seconds, args.duration_seconds)
    result = evaluate(turns, reference, args.duration_seconds, args.frame_ms)
    result["inputs"] = {
        "report": str(args.report),
        "reportSha256": _sha256(args.report),
        "referenceRttm": str(args.reference_rttm),
        "referenceRttmSha256": _sha256(args.reference_rttm),
        "referenceOffsetSeconds": args.reference_offset_seconds,
        "cycleIndex": args.cycle_index,
    }
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
