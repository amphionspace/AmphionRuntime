#!/usr/bin/env python3
"""Freeze paired diarization inputs, score captures, and veto candidate regressions.

Raw audio and caller transcripts stay outside Git. A manifest is created once;
changing any input, protocol or evaluator requires a new manifest. Missing
evidence never becomes a release PASS. No reference count is sent to the SDK.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import wave

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.delivery.device_stress_metrics import diarization_memory_verdict

import analyze_diarization_diagnostics as diagnostics
import evaluate_speaker_diarization_report as scorer


PROTOCOL = {
    "sampleRateHz": 16000, "channels": 1, "sampleWidthBytes": 2,
    "frameMs": 10, "collarSeconds": 0, "overlapIncluded": True,
    "mapping": "per-recording maximum overlap one-to-one; unmatched labels count as errors",
    "frameSampling": "frame centers; trailing partial frame excluded",
    "identityCollarSeconds": 0.25,
    "paceMs": 20, "maxSpeakers": 4, "oracleSpeakerCount": False,
}
GATES = ("identityAccuracy", "readability", "identityStability", "honesty",
         "realtime", "memory", "lifecycle", "offline")
ARTIFACTS = ("amphion_asr_demo.hap", "amphion_asr.har", "amphion_dingqiao.har",
             "amphion_police.har", "sherpa_onnx.har")


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path: Path, value: dict) -> None:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(encoded)


def file_record(path: Path) -> dict:
    path = path.expanduser().resolve(strict=True)
    return {"path": str(path), "sha256": scorer._sha256(path)}


def verify_file(record: dict) -> Path:
    path = Path(record["path"])
    if scorer._sha256(path) != record["sha256"]:
        raise ValueError(f"evidence hash changed: {path}")
    return path


def freeze(spec: dict, root: Path) -> dict:
    cases, ids = [], set()
    for source in spec["cases"]:
        item = dict(source)
        if item["id"] in ids:
            raise ValueError("duplicate case id")
        ids.add(item["id"])
        if item["tier"] not in {"public", "anchor", "recordings", "long"}:
            raise ValueError("invalid tier")
        for key in ("audio", "referenceRttm"):
            if key in item:
                item[key] = file_record(root / item[key])
        if item.get("expectedInputSha256", item["audio"]["sha256"]) != item["audio"]["sha256"]:
            raise ValueError(f"{item['id']}: indexed audio hash mismatch")
        with wave.open(item["audio"]["path"], "rb") as wav:
            geometry = (wav.getframerate(), wav.getnchannels(), wav.getsampwidth())
            if geometry != (16000, 1, 2) or wav.getcomptype() != "NONE":
                raise ValueError(f"{item['id']}: expected 16 kHz mono PCM16 WAV")
            item["frames"] = wav.getnframes()
            item["durationSeconds"] = wav.getnframes() / 16000
            item["pcmSha256"] = hashlib.sha256(wav.readframes(wav.getnframes())).hexdigest()
        for field in ("sourceOffsetSeconds", "referenceOffsetSeconds"):
            value = item.get(field, 0)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"invalid {field}")
            item[field] = value
        if not item.get("normalization") or not item.get("annotationStatus"):
            raise ValueError("normalization and annotationStatus must be explicit")
        if "referenceRttm" in item:
            reference = scorer._load_reference(Path(item["referenceRttm"]["path"]),
                                              item["referenceOffsetSeconds"], item["durationSeconds"])
            if not reference:
                raise ValueError("reference has no speech in the selected interval")
            item["referenceSpeakerCountForEvaluationOnly"] = len({r[2] for r in reference})
        cases.append(item)
    if not cases:
        raise ValueError("empty evaluation cohort")
    value = {"schemaVersion": 1, "scope": spec["scope"], "protocol": PROTOCOL,
             "officialComparable": False,
             "officialComparisonReason": "fixed diagnostic subset; no same-input official full-corpus baseline",
             "cases": cases, "evaluator": file_record(Path(scorer.__file__))}
    value["manifestSha256"] = digest(value)
    return value


def verify_manifest(manifest: dict) -> None:
    body = {key: value for key, value in manifest.items() if key != "manifestSha256"}
    if digest(body) != manifest.get("manifestSha256"):
        raise ValueError("manifest changed after freeze")
    if manifest["protocol"] != PROTOCOL:
        raise ValueError("unsupported scoring protocol")
    if scorer._sha256(Path(scorer.__file__)) != manifest["evaluator"]["sha256"]:
        raise ValueError("scorer changed; freeze a new evaluation manifest")
    for case in manifest["cases"]:
        verify_file(case["audio"])
        if "referenceRttm" in case:
            verify_file(case["referenceRttm"])


def binding_errors(binding: dict) -> list[str]:
    errors = []
    commit = binding.get("commit", "")
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        errors.append("missing full runtime commit")
    for key in ("device", "systemVersion", "sourceFingerprint"):
        if not binding.get(key):
            errors.append(f"missing {key}")
    artifacts = binding.get("artifacts", {})
    for name in ARTIFACTS:
        record = artifacts.get(name, {})
        if not record.get("path") or not record.get("sha256"):
            errors.append(f"missing artifact: {name}")
        else:
            verify_file(record)
    return errors


def runtime_evidence(report: dict, events: list[dict]) -> dict:
    memory = report.get("memory", {})
    memory_assessment = diarization_memory_verdict(memory)
    # Neither a generic alarm nor a fall at model teardown proves a same-phase
    # memory regression/stability result. A hash-bound review can supply it.
    memory_status = "FAIL" if memory_assessment.get("status") == "FAIL" else "INCONCLUSIVE"
    sessions = {}
    for event in events:
        if event.get("sessionId"):
            sessions.setdefault(event["sessionId"], []).append(event)
    realtime = []
    for session, items in sessions.items():
        points = [e["fields"] for e in items if e["event"] == "DIARIZATION_QUEUE"]
        status = "INCONCLUSIVE"
        delays = [p["audioDelayMs"] for p in points if isinstance(p.get("audioDelayMs"), (int, float))]
        pending = [p["pendingJobs"] for p in points if isinstance(p.get("pendingJobs"), (int, float))]
        valid = len(delays) == len(points) == len(pending) and bool(points)
        if valid and max(pending) > 2:
            status = "FAIL"
        elif valid and len(points) >= 6 and any(e["event"] == "DIARIZATION_DRAINED" for e in items):
            span = (points[-1].get("audioEndSample", 0) - points[0].get("audioEndSample", 0))/16000
            third = len(delays)//3
            head, tail = statistics.median(delays[:third]), statistics.median(delays[-third:])
            # The 10 s bound is the existing native input window, not a new wait
            # or timeout. Positive drift stays inconclusive for targeted review.
            if span > 60 and max(delays) <= 10000 and tail <= head:
                status = "PASS"
        realtime.append({"session": session, "status": status,
                         "queueSamples": len(points), "maxAudioDelayMs": max(delays, default=None)})
    state = "FAIL" if any(r["status"] == "FAIL" for r in realtime) else (
        "PASS" if realtime and all(r["status"] == "PASS" for r in realtime) else "INCONCLUSIVE")
    return {"realtime": state, "memory": memory_status, "sessions": realtime,
            "memoryObservation": memory, "memoryAssessment": memory_assessment}


def assess(manifest: dict, captures: dict) -> dict:
    verify_manifest(manifest)
    binding = captures.get("binding", {})
    missing_binding = binding_errors(binding)
    results = {}
    unknown_ids = set(captures.get("cases", {})) - {c["id"] for c in manifest["cases"]}
    if unknown_ids:
        raise ValueError(f"unknown capture cases: {sorted(unknown_ids)}")
    for case in manifest["cases"]:
        capture = captures.get("cases", {}).get(case["id"], {})
        result = {"tier": case["tier"], "durationSeconds": case["durationSeconds"],
                  "inputSha256": case["audio"]["sha256"],
                  "referenceRttmSha256": case.get("referenceRttm", {}).get("sha256"),
                  "gates": {name: "INCONCLUSIVE" for name in GATES}, "evidence": {}}
        if capture:
            if capture.get("inputSha256") != case["audio"]["sha256"]:
                raise ValueError(f"{case['id']}: capture input mismatch")
            if capture.get("bindingSha256") != digest(binding):
                raise ValueError(f"{case['id']}: capture artifact/device binding mismatch")
        report = None
        if capture.get("report"):
            report_path = verify_file(capture["report"])
            report = read(report_path)
            result["evidence"]["report"] = capture["report"]
            cycle_index = capture.get("cycleIndex", 0)
            turns = scorer._decode_turns(report, cycle_index)
            result["captureBindingIssues"] = []
            actual = report.get("build_identity", {})
            if (report.get("device") != binding.get("device") or
                    actual.get("git_commit") != binding.get("commit") or
                    not actual.get("source_fingerprint_sha256") or
                    actual.get("source_fingerprint_sha256") != binding.get("sourceFingerprint")):
                result["captureBindingIssues"].append("report does not bind the declared runtime/device")
            for name, record in binding.get("artifacts", {}).items():
                if actual.get("artifacts", {}).get(name, {}).get("sha256") != record["sha256"]:
                    result["captureBindingIssues"].append(f"report artifact mismatch: {name}")
            if capture.get("corpus"):
                corpus = read(verify_file(capture["corpus"]))
                entry = next((i for i in corpus if i["id"] == report["cycles"][cycle_index]["id"]), None)
                if entry is None or entry["source_sha256"] != case["audio"]["sha256"] or entry["pcm_sha256"] != case["pcmSha256"]:
                    raise ValueError(f"{case['id']}: report PCM mapping mismatch")
                result["evidence"]["corpus"] = capture["corpus"]
            else:
                result["captureBindingIssues"].append("missing report PCM input map")
            if "referenceRttm" in case:
                reference = scorer._load_reference(Path(case["referenceRttm"]["path"]),
                                                  case["referenceOffsetSeconds"], case["durationSeconds"])
                result["metrics"] = scorer.evaluate(turns, reference, case["durationSeconds"])
            # The stress carrier's PASS is only an interface result, never an identity verdict.
            result["sdkOverallStatus"] = report.get("overall_status", report.get("overallStatus"))
            if diarization_memory_verdict(report.get("memory", {})).get("status") == "FAIL":
                result["gates"]["memory"] = "FAIL"
            if report.get("diarization_lifecycle", {}).get("status") == "FAIL":
                result["gates"]["lifecycle"] = "FAIL"
            if report.get("native_streams", {}).get("status") == "FAIL":
                result["gates"]["lifecycle"] = "FAIL"
        if capture.get("events"):
            events_path = verify_file(capture["events"])
            result["evidence"]["events"] = capture["events"]
            caller = None
            if capture.get("caller"):
                caller = read(verify_file(capture["caller"]))
                result["evidence"]["caller"] = capture["caller"]
            events = diagnostics.load_events(events_path)
            analysis = diagnostics.summarize(events, caller=caller)
            result["diagnostics"] = analysis
            if result["gates"]["lifecycle"] != "FAIL":
                result["gates"]["lifecycle"] = analysis["lifecycle"]["status"]
            if analysis["queue"]["status"] == "FAIL":
                result["gates"]["realtime"] = "FAIL"
            if report:
                runtime = runtime_evidence(report, events)
                result["runtime"] = runtime
                for gate in ("memory", "realtime"):
                    if result["gates"][gate] != "FAIL":
                        result["gates"][gate] = runtime[gate]
        # Review files contain interval assertions plus exact evidence hashes. They
        # are deliberately separate from scalar accuracy scores and MOSS output.
        if capture.get("review"):
            review = read(verify_file(capture["review"]))
            expected = {key: value["sha256"] for key, value in result["evidence"].items()}
            if (review.get("inputSha256") != case["audio"]["sha256"] or
                    review.get("bindingSha256") != digest(binding) or
                    review.get("captureHashes") != expected or not expected):
                raise ValueError(f"{case['id']}: review does not bind the captured evidence")
            for gate, assertions in review.get("assertions", {}).items():
                if gate not in GATES or not assertions:
                    raise ValueError("invalid review gate or empty assertions")
                states = []
                for assertion in assertions:
                    state = assertion.get("status")
                    if state not in {"PASS", "FAIL", "INCONCLUSIVE"} or not assertion.get("evidence"):
                        raise ValueError("review needs an explicit status and evidence")
                    states.append(state)
                verdict = "FAIL" if "FAIL" in states else "PASS" if set(states) == {"PASS"} else "INCONCLUSIVE"
                if result["gates"][gate] != "FAIL":
                    result["gates"][gate] = verdict
            result["evidence"]["review"] = capture["review"]
        results[case["id"]] = result
        missing_binding.extend(f"{case['id']}: {issue}" for issue in result.get("captureBindingIssues", []))
    return {"schemaVersion": 1, "manifestSha256": manifest["manifestSha256"],
            "binding": binding, "bindingIssues": missing_binding,
            "results": results, "releaseStatus": release_status(results, missing_binding)}


def release_status(results: dict, binding_issues: list) -> str:
    gates = [s for item in results.values() for s in item["gates"].values()]
    if "FAIL" in gates:
        return "FAIL"
    tiers = {item["tier"] for item in results.values()}
    anchors = sum(item["tier"] == "anchor" for item in results.values())
    recordings = sum(item["tier"] in {"anchor", "recordings"} for item in results.values())
    long_run = any(item["tier"] == "long" and item["durationSeconds"] >= 600 for item in results.values())
    if (binding_issues or not gates or set(gates) != {"PASS"} or
            not {"public", "anchor", "recordings", "long"} <= tiers or
            anchors < 4 or recordings < 17 or not long_run):
        return "INCONCLUSIVE"
    return "PASS"


def compare(baseline: dict, candidate: dict) -> dict:
    if baseline["manifestSha256"] != candidate["manifestSha256"]:
        raise ValueError("unpaired manifest: protocol, evaluator or cohort differs")
    for field in ("device", "systemVersion"):
        if baseline["binding"].get(field) != candidate["binding"].get(field):
            raise ValueError(f"unpaired {field}")
    if baseline["results"].keys() != candidate["results"].keys():
        raise ValueError("unpaired case set")
    regressions, deltas, uncertain, existing, unattributed = [], {}, [], [], []
    for name, before in baseline["results"].items():
        after = candidate["results"][name]
        for key in ("inputSha256", "referenceRttmSha256", "tier"):
            if before[key] != after[key]:
                raise ValueError(f"{name}: unpaired {key}")
        for gate in GATES:
            old, new = before["gates"][gate], after["gates"][gate]
            if new == "FAIL":
                if old == "FAIL":
                    existing.append(f"{name}:{gate}:FAIL")
                elif old == "PASS":
                    regressions.append(f"{name}:{gate}:PASS->FAIL")
                else:
                    unattributed.append(f"{name}:{gate}:{old}->FAIL; baseline not verified")
            elif new != "PASS":
                uncertain.append(f"{name}:{gate}:{old}->{new}")
        b, c = before.get("metrics"), after.get("metrics")
        if b is None or c is None:
            if before["tier"] == "public":
                uncertain.append(f"{name}:missing public metrics")
            continue
        if c["speakerCountError"] < min(0, b["speakerCountError"]):
            regressions.append(f"{name}:new speaker-count collapse")
        for speaker, recall in b["perSpeakerRecall"].items():
            if recall > 0 and c["perSpeakerRecall"].get(speaker, 0) == 0:
                regressions.append(f"{name}:{speaker}:new zero recall")
        old_labels = b["identityStability"]["perReferenceLabelSeconds"]
        new_labels = c["identityStability"]["perReferenceLabelSeconds"]
        for speaker, labels in old_labels.items():
            old_count = sum(key.isdigit() for key in labels)
            new_count = sum(key.isdigit() for key in new_labels.get(speaker, {}))
            if new_count > max(1, old_count):
                regressions.append(f"{name}:{speaker}:more named identities")
        for metric in ("detectedOverlapSeconds", "secondaryEvidenceSeconds"):
            if b[metric] > 0 and c[metric] == 0:
                regressions.append(f"{name}:{metric}:evidence lost")
        # Less UNKNOWN and more switches can be legitimate corrections. Require
        # interval evidence; never infer correctness from a lower scalar alone.
        if c["unknownTurnSeconds"] < b["unknownTurnSeconds"] and after["gates"]["honesty"] != "PASS":
            uncertain.append(f"{name}:UNKNOWN reduction needs interval review")
        deltas[name] = {key: c[key] - b[key] for key in (
            "der", "missedSpeechSeconds", "falseAlarmSeconds", "speakerConfusionSeconds",
            "unknownTurnSeconds", "minoritySpeakerRecall", "overlapDetectionRecall")}
    status = "FAIL" if regressions or existing or unattributed else "INCONCLUSIVE" if (
        uncertain or baseline["bindingIssues"] or candidate["bindingIssues"]) else "PASS"
    return {"status": status, "regressions": regressions, "existingFailures": existing,
            "unattributedFailures": unattributed, "unverified": uncertain,
            "baselineBindingIssues": baseline["bindingIssues"],
            "candidateBindingIssues": candidate["bindingIssues"],
            "metricDeltas": deltas, "officialNumbersAreReleaseThresholds": False,
            "releaseStatus": "PASS" if status == "PASS" and candidate["releaseStatus"] == "PASS" else
                             "FAIL" if status == "FAIL" or candidate["releaseStatus"] == "FAIL" else "INCONCLUSIVE"}


def run_tier(manifest: dict, tier: str, output: Path, prior: dict | None = None) -> dict:
    verify_manifest(manifest)
    required = {"anchor"} if tier == "recordings" else {"anchor", "recordings"} if tier == "long" else set()
    if required:
        if not prior or prior.get("manifestSha256") != manifest["manifestSha256"] or prior.get("bindingIssues"):
            raise ValueError("full replay requires a paired, source-bound prior assessment")
        for case in manifest["cases"]:
            if case["tier"] in required:
                gates = prior.get("results", {}).get(case["id"], {}).get("gates", {})
                if set(gates) != set(GATES) or set(gates.values()) != {"PASS"}:
                    raise ValueError(f"{case['id']}: resolve anchor/recording gates before expanding the run")
        # Existing build identity verifier checks the actual HAR/HAP bytes. The
        # previous tier must bind that same build, not a candidate switched later.
        from run_device_stress import verified_build_identity
        identity = verified_build_identity()
        if any(identity["artifacts"][name]["sha256"] != prior["binding"]["artifacts"][name]["sha256"] for name in ARTIFACTS):
            raise ValueError("artifact changed between tiers")
    selected = [case for case in manifest["cases"] if case["tier"] == tier]
    if not selected:
        raise ValueError("empty tier")
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for case in selected:
        directory = output / case["id"]
        audio = directory / "input"
        audio.mkdir(parents=True)
        (audio / "input.wav").symlink_to(case["audio"]["path"])
        # Window mode intentionally requires two public batches. Short clips
        # use the existing paced+diarization lifecycle carrier; their identity
        # and text assertions live in the paired evaluation, not a fake tail.
        mode = "diarization-windows" if case["durationSeconds"] > 120 else "paced"
        command = [sys.executable, str(Path(__file__).with_name("run_device_stress.py")),
                   "--data-dir", str(audio), "--mode", mode, "--enable-diarization",
                   "--cycles", "1", "--files", "1", "--pace-ms", "20", "--skip-build-install",
                   "--output-root", str(directory / "device")]
        with (directory / "console.log").open("x") as stream:
            completed = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
        # Capture immediately: later sessions must not overwrite the diagnostic
        # source. Do this even after a failed carrier run.
        collect = [sys.executable, str(Path(__file__).with_name("collect_asr_diagnostics.py")),
                   "--last", "1", "--output-root", str(directory / "diagnostics")]
        collected_code = None
        if list((directory / "device").glob("*/report.json")):
            with (directory / "collection.log").open("x") as stream:
                collected_code = subprocess.run(collect, stdout=stream, stderr=subprocess.STDOUT).returncode
        results.append({"id": case["id"], "inputSha256": case["audio"]["sha256"],
                        "mode": mode, "carrierExitCode": completed.returncode, "captureExitCode": collected_code})
        write_new(directory / "run.json", results[-1])
        if completed.returncode or collected_code != 0:
            break
    summary = {"manifestSha256": manifest["manifestSha256"], "tier": tier, "runs": results,
               "status": "CAPTURED" if len(results) == len(selected) and all(
                   r["carrierExitCode"] == r["captureExitCode"] == 0 for r in results) else "FAIL",
               "releaseStatus": "INCONCLUSIVE", "reason": "captured SDK calls still require paired evaluation and real-caller review"}
    write_new(output / "run-summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("freeze")
    p.add_argument("--spec", type=Path, required=True)
    p.add_argument("--data-root", type=Path, required=True)
    p = commands.add_parser("evaluate")
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--captures", type=Path, required=True)
    p = commands.add_parser("compare")
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p = commands.add_parser("run")
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--tier", choices=("public", "anchor", "recordings", "long"), required=True)
    p.add_argument("--prior-assessment", type=Path)
    for p in commands.choices.values():
        p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        result = run_tier(read(args.manifest), args.tier, args.output,
                          read(args.prior_assessment) if args.prior_assessment else None)
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result["status"] == "FAIL" else 2
    if args.command == "freeze":
        result = freeze(read(args.spec), args.data_root.expanduser())
    elif args.command == "evaluate":
        result = assess(read(args.manifest), read(args.captures))
    else:
        result = compare(read(args.baseline), read(args.candidate))
    write_new(args.output, result)
    status = result.get("releaseStatus", "PASS")
    print(json.dumps({"output": str(args.output), "status": status}, ensure_ascii=False))
    return {"PASS": 0, "FAIL": 1, "INCONCLUSIVE": 2}[status]


if __name__ == "__main__":
    raise SystemExit(main())
