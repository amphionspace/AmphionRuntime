#!/usr/bin/env python3
"""Verify hash-bound Community encoder runtime observations without exposing tensors.

PASS covers the explicit carrier export and successful encoder Run observations.
It does not prove that every graph operator used NPU, that pooling/ASR avoided CPU,
or that installed device binaries were hashed by the SDK at runtime.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import statistics
import sys
import zipfile


WINDOW = "DIARIZATION_COMMUNITY_WINDOW"
ARTIFACTS = ("amphion_asr_demo.hap", "amphion_asr.har", "amphion_police.har",
             "amphion_dingqiao.har", "sherpa_onnx.har")
SCOPE = ("Controlled-carrier-export binding and successful encoder Run observations; "
         "not proof of all-operator NPU placement, no CPU fallback within the graph, "
         "recognition/identity accuracy, offline network behavior, or runtime binary hashing.")


def _number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _integer(value: object) -> bool:
    return _number(value) and value >= 0 and int(value) == value


def _id(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]+", value))


def _sha(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_record(path: Path) -> dict:
    path = path.resolve(strict=True)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path), "sha256": digest.hexdigest()}


def _object(data: bytes) -> dict:
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("metadata must be an object")
    return value


def _vector_issues(fields: dict) -> list[str]:
    issues = []
    segments = fields.get("segmentations")
    if segments is not None and (not isinstance(segments, list) or len(segments) != 589 * 3 or
                                 any(value not in (0, 1) or isinstance(value, bool) for value in segments)):
        issues.append("invalid-segmentation-geometry")
        segments = None
    if "embeddings" in fields:
        vectors = fields["embeddings"]
        if not isinstance(vectors, list) or len(vectors) != 3 * 256:
            issues.append("invalid-embedding-geometry")
        else:
            for channel in range(3):
                vector = vectors[channel*256:(channel+1)*256]
                if all(_number(value) for value in vector):
                    continue
                inactive = segments is not None and not any(segments[channel::3])
                sentinel = all(value is None or isinstance(value, float) and math.isnan(value) for value in vector)
                if not (inactive and sentinel):
                    issues.append("invalid-embedding-vector")
                    break
    if "runEmbeddings" in fields:
        vectors, ranges = fields["runEmbeddings"], fields.get("runRanges")
        if (not isinstance(vectors, list) or not isinstance(ranges, list) or len(ranges) % 4 or
                len(vectors) != len(ranges)//4 * 256):
            issues.append("invalid-run-embedding-geometry")
        else:
            for row in range(len(ranges)//4):
                local, channel, begin, end = ranges[row*4:row*4+4]
                if (not all(_integer(value) for value in (local, channel, begin, end)) or
                        local != 0 or channel >= 3 or not begin < end <= 589):
                    issues.append("invalid-run-range")
                    break
                channel, begin, end = int(channel), int(begin), int(end)
                vector = vectors[row*256:(row+1)*256]
                if all(_number(value) for value in vector):
                    continue
                # Native blocked/overlap runs are all-NaN, serialized as null.
                blocked = segments is not None and any(
                    not segments[frame*3+channel] or sum(segments[frame*3:frame*3+3]) != 1
                    for frame in range(begin, end))
                sentinel = all(value is None or isinstance(value, float) and math.isnan(value) for value in vector)
                if not (blocked and sentinel):
                    issues.append("invalid-run-embedding-vector")
                    break
    return issues


def check_windows(events: list[dict], *, require_backend: str = "npu", require_device: str = "kirin") -> dict:
    errors, timings, backend_counts, device_counts = [], [], Counter(), Counter()
    device_backends = Counter()
    jobs, starts, sequence, window_count = set(), set(), 0, 0
    vector_windows = 0
    for index, event in enumerate(events):
        fields = event.get("fields", {})
        current = event.get("sequence")
        if not _integer(current) or current <= sequence:
            errors.append({"code": "invalid-or-repeated-sequence", "eventIndex": index})
        else:
            if current != sequence + 1:
                errors.append({"code": "missing-journal-sequence", "eventIndex": index})
            sequence = current
        if event.get("event") in {"CALLBACK_ERROR", "RUNTIME_NATIVE_ERROR", "RUNTIME_DECODE_ERROR",
                                   "DIARIZATION_ERROR", "DIARIZATION_DEGRADED", "DIARIZATION_INFERENCE_ERROR"}:
            errors.append({"code": "runtime-error-observed", "eventIndex": index})
        if event.get("event") != WINDOW:
            continue
        window_index = window_count
        window_count += 1
        def error(code: str) -> None:
            errors.append({"code": code, "eventIndex": index, "windowIndex": window_index})
        if not isinstance(fields, dict):
            error("missing-window-fields")
            continue
        backend, device = fields.get("encoderBackend"), fields.get("encoderDevice")
        backend_valid = isinstance(backend, str) and backend in {"npu", "cpu"}
        backend_label = backend if backend_valid else "invalid"
        backend_counts[backend_label] += 1
        device_label = device if isinstance(device, str) and re.fullmatch(r"[A-Za-z0-9_. -]{1,80}", device) else "invalid"
        device_counts[device_label] += 1
        device_backends[(device_label, backend_label)] += 1
        if not backend_valid:
            error("missing-or-invalid-backend")
        elif require_backend != "any" and backend != require_backend:
            error("wrong-backend")
        if device_label == "invalid":
            error("missing-or-invalid-device")
        elif require_device and require_device.casefold() not in device.casefold():
            error("wrong-device")
        timing = fields.get("encoderMs")
        if not _number(timing) or timing < 0:
            error("missing-or-invalid-encoder-time")
        else:
            timings.append(timing)
        session, job, start = event.get("sessionId"), fields.get("jobId"), fields.get("windowStartSample")
        if not _id(session) or not _id(job) or not _integer(start):
            error("invalid-window-identity")
        else:
            if (session, job) in jobs or (session, start) in starts:
                error("duplicate-window")
            jobs.add((session, job))
            starts.add((session, start))
        if any(fields.get(key) for key in ("error", "encoderError")):
            error("window-error-observed")
        vector_windows += int("embeddings" in fields or "runEmbeddings" in fields)
        for issue in _vector_issues(fields):
            error(issue)
    if not window_count:
        errors.append({"code": "no-community-windows", "eventIndex": None})
    ordered = sorted(timings)
    return {"status": "FAIL" if errors else "PASS", "windowCount": window_count,
            "windowsWithVectorEvidence": vector_windows,
            "observedBackendCounts": dict(backend_counts), "observedDeviceCounts": dict(device_counts),
            "observedDeviceBackendCounts": [
                {"device": device, "backend": backend, "count": count}
                for (device, backend), count in sorted(device_backends.items())],
            "encoderMs": {"min": min(ordered, default=None),
                          "median": statistics.median(ordered) if ordered else None,
                          "p95": ordered[math.ceil(len(ordered)*0.95)-1] if ordered else None,
                          "max": max(ordered, default=None)},
            "firstErrorIndex": errors[0].get("eventIndex") if errors else None,
            "errors": errors}


def _load_capture(source: Path, report: dict) -> tuple[bytes, dict[str, bytes], dict]:
    run_id = report.get("run_id", "")
    diagnostic_id = report.get("diagnostics", {}).get("run_id", "")
    if run_id and not _id(run_id) or diagnostic_id and not _id(diagnostic_id):
        raise ValueError("invalid report run identity")
    marker = f"stress-binding-{run_id}.json"
    names = ("manifest.json", "summary.json", "effective-config.json", "build-identity.json",
             "events.ndjson", "callbacks.ndjson", "events.full.ndjson", marker)
    records = {"files": {}}
    if source.suffix.lower() == ".zip":
        records["zip"] = file_record(source)
        with zipfile.ZipFile(source) as archive:
            members = archive.namelist()
            if len(members) != len(set(members)) or any(
                    PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts for name in members):
                raise ValueError("ambiguous archive members")
            roots = [PurePosixPath(name).parent for name in members if name.endswith("/manifest.json")]
            candidates = [root for root in roots if not diagnostic_id or root.name == diagnostic_id]
            if len(candidates) != 1:
                raise ValueError("explicit diagnostic run does not identify one archive directory")
            root = candidates[0]
            metadata = {name: archive.read(str(root / name)) for name in names if str(root / name) in members}
            collection = root.parent / "collection.json"
            if str(collection) in members:
                data = archive.read(str(collection))
                value = _object(data)
                if root.name not in value.get("runIds", []) or value.get("runCount") != len(value.get("runIds", [])):
                    raise ValueError("collection run identity mismatch")
                metadata["collection.json"] = data
            for name, data in metadata.items():
                records["files"][name] = {"member": str(root.parent / name if name == "collection.json" else root / name),
                                          "sha256": _digest(data)}
        events = metadata.get("events.full.ndjson")
    else:
        directory = source if source.is_dir() else source.parent
        metadata = {name: (directory / name).read_bytes() for name in names if (directory / name).is_file()}
        for name in metadata:
            records["files"][name] = file_record(directory / name)
        if source.is_dir():
            events = metadata.get("events.full.ndjson")
        else:
            if source.name != "events.full.ndjson" and "manifest.json" in metadata:
                raise ValueError("use the full journal, not a bounded events snapshot")
            events = source.read_bytes()
            records["events"] = file_record(source)
    if events is None:
        raise ValueError("missing full diagnostic journal")
    return events, metadata, records


def verify_capture(source: Path, report_path: Path, identity_path: Path, *, requested_backend: str,
                   require_backend: str = "npu", require_device: str = "kirin") -> dict:
    if requested_backend not in {"cpu", "npu", "auto"} or require_backend not in {"cpu", "npu", "any"}:
        raise ValueError("unsupported encoder backend")
    report, identity = _object(report_path.read_bytes()), _object(identity_path.read_bytes())
    raw, metadata, inputs = _load_capture(source, report)
    events = []
    for line_number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        value = _object(line)
        if not isinstance(value.get("event"), str) or not isinstance(value.get("fields", {}), dict):
            raise ValueError(f"invalid event structure at line {line_number}")
        events.append(value)
    result = check_windows(events, require_backend=require_backend, require_device=require_device)
    result.update({"schemaVersion": 1, "scopeStatement": SCOPE,
                   "requestedBackend": requested_backend, "requiredBackend": require_backend,
                   "requiredDevice": require_device, "windowChecksStatus": result["status"]})
    inputs.update({"report": file_record(report_path), "sourceIdentity": file_record(identity_path)})
    inputs["eventsSha256"] = _digest(raw)
    inputs["inputCorpusSha256"] = report.get("input_corpus_sha256") if _sha(report.get("input_corpus_sha256")) else None
    result["inputs"] = inputs
    binding_errors, missing = [], []
    def issue(code: str, index: int | None = None) -> None:
        binding_errors.append({"code": code, "eventIndex": index})
    if report.get("configuration", {}).get("diarization_encoder") != requested_backend:
        issue("requested-backend-mismatch")
    actual = report.get("build_identity", {})
    source_fingerprint = identity.get("source_fingerprint_sha256")
    if not _sha(source_fingerprint) or not _sha(actual.get("source_fingerprint_sha256")):
        missing.append("source-fingerprint")
    elif actual["source_fingerprint_sha256"] != source_fingerprint:
        issue("foreign-source-build")
    artifact_hashes = {}
    for name in ARTIFACTS:
        expected = identity.get("artifacts", {}).get(name, {}).get("sha256")
        captured = actual.get("artifacts", {}).get(name, {}).get("sha256")
        if not _sha(expected) or not _sha(captured):
            missing.append(f"artifact:{name}")
        elif expected != captured:
            issue(f"foreign-artifact:{name}")
        else:
            artifact_hashes[name] = expected
    result["buildIdentity"] = {"sourceFingerprintSha256": source_fingerprint if _sha(source_fingerprint) else None,
                               "artifactSha256": artifact_hashes,
                               "scope": "Explicit local source/artifact identity matched to runner metadata; SDK binaryHashStatus is not proof."}
    if report.get("overall_status") == "FAIL":
        issue("runner-reported-failure")
    diagnostic = report.get("diagnostics", {})
    diagnostic_id = diagnostic.get("run_id")
    runner_id = report.get("run_id", "")
    marker_name = f"stress-binding-{runner_id}.json"
    marker = _object(metadata[marker_name]) if marker_name in metadata else {}
    manifest = _object(metadata["manifest.json"]) if "manifest.json" in metadata else {}
    summary = _object(metadata["summary.json"]) if "summary.json" in metadata else {}
    if diagnostic.get("status") == "FAIL":
        issue("runner-diagnostic-capture-failed")
    if diagnostic.get("status") != "CAPTURED" or not marker or not manifest or not summary:
        missing.append("controlled-carrier-export-binding")
    else:
        application = report.get("application", {})
        expected = {"schemaVersion": 1, "runnerRunId": report.get("run_id"),
                    "diagnosticRunId": diagnostic_id, "mode": report.get("mode"),
                    "diarizationEncoder": requested_backend,
                    "requestedCycles": report.get("configuration", {}).get("cycles")}
        try:
            expected["completedCycles"] = int(application["completed"])
        except (KeyError, TypeError, ValueError):
            missing.append("runner-completed-cycles")
        if any(marker.get(key) != value for key, value in expected.items()):
            issue("carrier-binding-mismatch")
        if any(not _integer(marker.get(key)) for key in ("requestedCycles", "completedCycles")):
            issue("invalid-carrier-cycle-count")
        if isinstance(report.get("cycles"), list) and marker.get("completedCycles") != len(report["cycles"]):
            issue("carrier-cycle-evidence-count-mismatch")
        if (application.get("diagnosticsRunId") != diagnostic_id or
                application.get("diagnosticsStatus") != "EXPORTED"):
            issue("runner-export-summary-mismatch")
        if (manifest.get("runId") != diagnostic_id or summary.get("runId") != diagnostic_id or
                manifest.get("fullEventJournal") != "events.full.ndjson" or
                manifest.get("fullEventJournalRunId") != diagnostic_id):
            issue("diagnostic-full-journal-run-mismatch")
        sessions = [session.get("sessionId") for session in summary.get("sessions", [])]
        if not all(_id(session) for session in sessions) or len(sessions) != len(set(sessions)) or marker.get("diagnosticSessions") != sessions:
            issue("diagnostic-session-binding-mismatch")
        if any(diagnostic.get("files", {}).get(name, {}).get("sha256") != _digest(data)
               for name, data in metadata.items() if name != "collection.json"):
            issue("diagnostic-file-hash-mismatch")
        for name in ("manifest.json", "summary.json", "events.full.ndjson", marker_name):
            if name not in diagnostic.get("files", {}):
                missing.append(f"capture-hash:{name}")
        start, finish = marker.get("startedAtMs"), marker.get("finishedAtMs")
        if not _number(start) or not _number(finish) or not 0 <= start <= finish:
            issue("invalid-carrier-workload-time")
            start = finish = None
        session_events = {session: [] for session in sessions if _id(session)}
        session_engines = {}
        for index, event in enumerate(events):
            if event.get("runId") != diagnostic_id:
                issue("foreign-diagnostic-event", index)
            session = event.get("sessionId", "")
            if session:
                if session not in session_events:
                    issue("foreign-diagnostic-session", index)
                else:
                    session_events[session].append((index, event))
                    owner = (event.get("engineId"), event.get("sessionGeneration"))
                    if not _id(owner[0]) or not _integer(owner[1]) or owner[1] == 0 or session_engines.get(session, owner) != owner:
                        issue("diagnostic-session-owner-mismatch", index)
                    session_engines[session] = owner
            if event.get("event") == WINDOW and start is not None:
                at = event.get("wallTimeMs")
                if not _number(at) or not start <= at <= finish:
                    issue("window-outside-carrier-workload", index)
        if "starts" in application:
            try:
                # recoveryStarts is -1 whenever the carrier mode has no finish-recovery phase,
                # so only a real, non-negative count may add to the expected session total.
                expected_starts = int(application["starts"]) + sum(
                    max(int(cycle.get("recoveryStarts", 0)), 0) for cycle in report.get("cycles", []))
                if expected_starts != sum(event.get("event") == "START_LISTENING" for event in events):
                    issue("runner-diagnostic-session-count-mismatch")
            except (TypeError, ValueError):
                issue("invalid-runner-session-count")
        for items in session_events.values():
            starts = [index for index, event in items if event.get("event") == "START_LISTENING"]
            lasts = [index for index, event in items if event.get("event") == "CALLBACK_RESULT" and event.get("fields", {}).get("isLast") is True]
            completes = [index for index, event in items if event.get("event") == "CALLBACK_COMPLETE"]
            cancels = [index for index, event in items if event.get("event") == "CANCEL_REQUESTED"]
            cancelled = bool(cancels)
            if len(starts) != 1:
                issue("missing-or-duplicate-session-start", items[0][0] if items else None)
            if not cancelled and (len(lasts) != 1 or len(completes) != 1 or lasts[0] >= completes[0]):
                issue("missing-or-invalid-terminal-callbacks", items[-1][0] if items else None)
            elif completes and any(index > completes[-1] and event.get("event", "").startswith("CALLBACK_") for index, event in items):
                issue("callback-after-complete", completes[-1])
            if cancels and any(index > cancels[0] and event.get("event") in {"CALLBACK_COMPLETE", "CALLBACK_RESULT"}
                               for index, event in items):
                issue("callback-after-cancel", cancels[0])
    result["captureBinding"] = {"status": "FAIL" if binding_errors else "INCONCLUSIVE" if missing else "PASS",
                                "missing": missing, "errors": binding_errors}
    result["errors"].extend(binding_errors)
    if result["errors"]:
        result["status"] = "FAIL"
        known = [error["eventIndex"] for error in result["errors"] if error.get("eventIndex") is not None]
        result["firstErrorIndex"] = min(known, default=None)
    elif missing:
        result["status"] = "INCONCLUSIVE"
    else:
        result["status"] = "PASS"
    result["kirinAcceptance"] = "PASS" if result["status"] == "PASS" and require_backend == "npu" and require_device.casefold() == "kirin" else "NOT_ESTABLISHED"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--events", type=Path)
    source.add_argument("--run-directory", type=Path)
    source.add_argument("--diagnostics-zip", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--build-identity", type=Path, required=True)
    parser.add_argument("--requested-backend", choices=("cpu", "npu", "auto"), required=True)
    parser.add_argument("--require-backend", choices=("cpu", "npu", "any"), default="npu")
    parser.add_argument("--require-device", default="kirin")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_capture(args.events or args.run_directory or args.diagnostics_zip, args.report,
                                args.build_identity, requested_backend=args.requested_backend,
                                require_backend=args.require_backend, require_device=args.require_device)
        encoded = json.dumps(result, indent=2, allow_nan=False) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile):
        print("[ERROR] invalid, missing, or already existing evidence; output not replaced", file=sys.stderr)
        return 1
    print(json.dumps({"status": result["status"], "windowCount": result["windowCount"],
                      "firstErrorIndex": result["firstErrorIndex"], "output": str(args.output)}))
    return {"PASS": 0, "FAIL": 1, "INCONCLUSIVE": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
