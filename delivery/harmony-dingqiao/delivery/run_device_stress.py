#!/usr/bin/env python3
"""Run repeatable real-audio stress tests against the Harmony Dingqiao SDK."""

from __future__ import annotations

import argparse
import audioop
import csv
import hashlib
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
import wave
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
PROJECT_ROOT = REPO_ROOT / "delivery" / "harmony-dingqiao"
BUILD_IDENTITY = PROJECT_ROOT / "build" / "smoke" / "build-identity.json"
BUILD_IDENTITY_TOOL = SCRIPT_DIR / "harmony_build_identity.py"
BUNDLE = "com.amphion.asr.harmony.demo"
MODULE = "amphion_asr_demo"
ABILITY = "EntryAbility"
REMOTE_ROOT = "/data/storage/el2/base/files/asr-stress"
FINISH_MODES = {
    "burst", "paced", "vad-begin", "reconfigure", "recreate", "max-duration",
    "continuous-max-duration", "continuous-long-session",
    "continuous-voiceprint-speaker-vad", "numeric-edge",
    "finish-shutdown", "finish-shutdown-relicense", "speaker-vad-shutdown-relicense",
    "customer-tap-vad", "customer-ptt", "customer-transcription", "customer-ptt-tail",
    "customer-form", "customer-meeting-minutes",
}
MIN_MEMORY_SAMPLES = 6
MIN_MEMORY_OBSERVATION_SECONDS = 15.0
MIN_MEMORY_SLOPE_SECONDS = 60.0
TARGET_SPEAKER_MODES = {
    "speaker-vad-turn",
    "target-speaker-enhancement",
    "target-speaker-enhancement-onstart",
    "target-speaker-enhancement-cancel",
}
VOICEPRINT_FALLBACK_FIXTURES = REPO_ROOT / "asr/test-fixtures/voiceprint-fallback"


@dataclass(frozen=True)
class AudioSource:
    path: Path
    sample_rate: int
    channels: int
    sample_width: int
    frames: int
    duration_seconds: float


@dataclass
class MemorySample:
    elapsed_seconds: float
    pid: int
    vm_rss_kb: int
    vm_hwm_kb: int
    vm_data_kb: int
    vm_swap_kb: int
    threads: int
    process_cpu_ticks: int = -1
    system_cpu_ticks: int = -1
    logical_cpus: int = 0


class StressFailure(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Drive the Harmony ASR SDK through a headless test carrier and check its contracts."
    )
    parser.add_argument("--data-dir", type=Path, default=Path.home() / "Downloads" / "testdata")
    parser.add_argument(
        "--target-speaker-manifest",
        type=Path,
        help="Role and text-assertion manifest for target-speaker fixtures.",
    )
    parser.add_argument(
        "--expected-tail-manifest",
        type=Path,
        help="SHA-256 keyed final-text suffix assertions for long-speech fixtures.",
    )
    parser.add_argument(
        "--mode",
        choices=(
            "burst",
            "paced",
            "vad-begin",
            "vad-begin-silence",
            "voiceprint",
            "voiceprint-fallback",
            "voiceprint-vad-begin",
            "voiceprint-vad-begin-idle",
            "cancel",
            "cancel-full",
            "recreate",
            "reconfigure",
            "max-duration",
            "continuous-max-duration",
            "continuous-long-session",
            "continuous-voiceprint-speaker-vad",
            "edge",
            "reentrant",
            "start-cancel",
            "start-write",
            "start-write-reload",
            "speaker-vad-onstart",
            "cold-start-pcm-gap",
            "speaker-vad-turn",
            "target-speaker-enhancement",
            "target-speaker-enhancement-onstart",
            "target-speaker-enhancement-cancel",
            "callback-api-reentrant",
            "customer-tap-vad",
            "customer-ptt",
            "customer-transcription",
            "customer-ptt-tail",
            "customer-form",
            "customer-meeting-minutes",
            "endpoint-reentrant",
            "finish-shutdown",
            "finish-shutdown-relicense",
            "speaker-vad-shutdown-relicense",
            "user-sequence",
            "numeric-edge",
        ),
        default="burst",
    )
    parser.add_argument("--cycles", type=int, default=100)
    parser.add_argument(
        "--files",
        type=int,
        default=24,
        help="Representative WAV count; 0 selects every valid WAV.",
    )
    parser.add_argument("--settle-ms", type=int, default=0)
    parser.add_argument("--pace-ms", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--sample-interval", type=float, default=1.0)
    parser.add_argument("--post-run-observe", type=float, default=5.0)
    parser.add_argument(
        "--speaker-vad-threshold",
        type=float,
        help="Override speakerVadThreshold for sequential speaker-turn experiments.",
    )
    parser.add_argument(
        "--skip-target-content-check",
        action="store_true",
        help="Keep lifecycle checks but skip the carrier's C1 text assertion.",
    )
    parser.add_argument("--max-rss-growth-mb", type=float, default=64.0)
    parser.add_argument("--max-thread-growth", type=int, default=2)
    parser.add_argument("--max-empty-final-rate", type=float, default=0.05)
    parser.add_argument("--skip-build-install", action="store_true")
    parser.add_argument(
        "--installed-package",
        action="store_true",
        help=(
            "Test the package already installed on the device and record its bundle identity; "
            "do not require or install a local build."
        ),
    )
    parser.add_argument("--device", default="", help=argparse.SUPPRESS)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "build" / "device-stress",
    )
    args = parser.parse_args()
    if args.cycles <= 0:
        parser.error("--cycles must be positive")
    if args.files < 0:
        parser.error("--files must be non-negative")
    if args.timeout <= 0 or args.sample_interval <= 0:
        parser.error("--timeout and --sample-interval must be positive")
    if args.settle_ms < 0 or args.pace_ms < 0 or args.post_run_observe < 0:
        parser.error("timing values must be non-negative")
    if args.skip_target_content_check and args.mode != "speaker-vad-turn":
        parser.error("--skip-target-content-check requires --mode speaker-vad-turn")
    if args.speaker_vad_threshold is not None:
        if args.mode != "speaker-vad-turn":
            parser.error("--speaker-vad-threshold requires --mode speaker-vad-turn")
        if not -1.0 <= args.speaker_vad_threshold <= 1.0:
            parser.error("--speaker-vad-threshold must be within [-1, 1]")
    if args.target_speaker_manifest is not None and args.mode not in TARGET_SPEAKER_MODES:
        parser.error("--target-speaker-manifest requires a target-speaker mode")
    tail_modes = {
        "customer-meeting-minutes", "customer-ptt-tail", "continuous-max-duration", "continuous-long-session",
        "continuous-voiceprint-speaker-vad",
    }
    if args.expected_tail_manifest is not None and args.mode not in tail_modes:
        parser.error("--expected-tail-manifest requires a tail-validation mode")
    if args.mode in tail_modes and args.expected_tail_manifest is None:
        parser.error(f"--mode {args.mode} requires --expected-tail-manifest")
    if args.mode == "continuous-long-session" and args.cycles < 2:
        parser.error("--mode continuous-long-session requires at least 2 cycles")
    if args.mode == "continuous-long-session" and args.pace_ms < 20:
        parser.error("--mode continuous-long-session requires --pace-ms >= 20")
    if (
        args.mode == "speaker-vad-turn"
        and not args.skip_target_content_check
        and args.target_speaker_manifest is None
    ):
        parser.error("speaker-vad-turn accuracy requires --target-speaker-manifest")
    if args.skip_build_install and args.installed_package:
        parser.error("--skip-build-install and --installed-package are mutually exclusive")
    return args


def run(command: list[str], *, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=check,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verified_build_identity() -> dict[str, object]:
    if not BUILD_IDENTITY.is_file():
        raise StressFailure(
            "missing Harmony build identity; build and install the current source before stress testing"
        )
    try:
        identity = json.loads(BUILD_IDENTITY.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StressFailure(f"cannot read Harmony build identity: {error}") from error
    if not isinstance(identity, dict):
        raise StressFailure("Harmony build identity must be a JSON object")
    build_mode = identity.get("build_mode")
    if build_mode not in ("debug", "diagnostics"):
        raise StressFailure("Harmony build identity has no supported build mode")
    result = run(
        [
            sys.executable,
            str(BUILD_IDENTITY_TOOL),
            "--verify",
            str(BUILD_IDENTITY),
            "--build-mode",
            str(build_mode),
        ],
        check=False,
    )
    if result.returncode != 0:
        raise StressFailure((result.stdout + result.stderr).strip())
    return identity


def parse_installed_bundle_info(text: str) -> dict[str, object]:
    start = text.find("{")
    if start < 0:
        raise StressFailure("installed bundle dump did not contain JSON")
    try:
        bundle = json.loads(text[start:])
    except json.JSONDecodeError as error:
        raise StressFailure(f"installed bundle dump is not valid JSON: {error}") from error
    if not isinstance(bundle, dict):
        raise StressFailure("installed bundle dump must be a JSON object")
    application = bundle.get("applicationInfo")
    if not isinstance(application, dict):
        raise StressFailure("installed bundle dump is missing applicationInfo")
    if application.get("bundleName") != BUNDLE:
        raise StressFailure(f"installed bundle identity does not match {BUNDLE}")
    return bundle


def installed_package_identity(hdc: Hdc) -> tuple[dict[str, object], dict[str, object]]:
    result = hdc.shell("bm", "dump", "-n", BUNDLE, check=False)
    if result.returncode != 0:
        raise StressFailure(f"cannot inspect installed bundle: {(result.stdout + result.stderr).strip()}")
    bundle = parse_installed_bundle_info(result.stdout)
    application = bundle["applicationInfo"]
    assert isinstance(application, dict)
    identity = {
        "source": "installed_package",
        "bundle_name": application.get("bundleName"),
        "version_name": application.get("versionName"),
        "version_code": application.get("versionCode"),
        "fingerprint": application.get("fingerprint"),
        "compile_sdk_version": application.get("compileSdkVersion"),
        "api_target_version": application.get("apiTargetVersion"),
        "cpu_abi": application.get("cpuAbi"),
        "debug": application.get("debug"),
    }
    return identity, bundle


class Hdc:
    def __init__(self, executable: Path, target: str):
        self.executable = executable
        self.target = target

    def command(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(self.executable), "-t", self.target, *args], check=check)

    def shell(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return self.command("shell", *args, check=check)

    def app_send(self, local: Path, remote: str) -> None:
        result = self.command("file", "send", "-b", BUNDLE, str(local), remote, check=False)
        if result.returncode != 0 or "[Fail]" in result.stdout + result.stderr:
            raise StressFailure(f"failed to send stress payload: {(result.stdout + result.stderr).strip()}")

    def app_recv(self, remote: str, local: Path) -> bool:
        result = self.command("file", "recv", "-b", BUNDLE, remote, str(local), check=False)
        return result.returncode == 0 and "[Fail]" not in result.stdout + result.stderr and local.is_file()


def locate_hdc() -> Path:
    deveco = Path(os.environ.get("DEVECO_STUDIO_HOME", "/Applications/DevEco-Studio.app/Contents"))
    hdc = deveco / "sdk" / "default" / "openharmony" / "toolchains" / "hdc"
    if not hdc.is_file():
        raise StressFailure(f"missing HDC: {hdc}")
    return hdc


def select_target(hdc: Path, requested: str) -> str:
    if requested:
        return requested
    result = run([str(hdc), "list", "targets"])
    targets = [line.strip() for line in result.stdout.replace("\r", "").splitlines() if line.strip()]
    if len(targets) != 1:
        raise StressFailure(f"expected exactly one connected HDC target, found {len(targets)}")
    return targets[0]


def inspect_wavs(root: Path) -> list[AudioSource]:
    if not root.is_dir():
        raise StressFailure(f"audio data directory does not exist: {root}")
    sources: list[AudioSource] = []
    for path in sorted(root.rglob("*.wav")):
        if path.name.startswith("._") or "__MACOSX" in path.parts:
            continue
        try:
            with wave.open(str(path), "rb") as wav:
                if wav.getcomptype() != "NONE":
                    continue
                frames = wav.getnframes()
                sample_rate = wav.getframerate()
                channels = wav.getnchannels()
                sample_width = wav.getsampwidth()
        except (EOFError, OSError, wave.Error):
            continue
        if frames <= 0 or sample_rate <= 0:
            continue
        sources.append(
            AudioSource(
                path=path,
                sample_rate=sample_rate,
                channels=channels,
                sample_width=sample_width,
                frames=frames,
                duration_seconds=frames / sample_rate,
            )
        )
    if not sources:
        raise StressFailure(f"no valid PCM WAV files found under {root}")
    return sources


def quantile_pick(items: list[AudioSource], count: int) -> list[AudioSource]:
    if count >= len(items):
        return list(items)
    ordered = sorted(items, key=lambda item: (item.duration_seconds, str(item.path)))
    if count == 1:
        return [ordered[len(ordered) // 2]]
    indexes = [round(i * (len(ordered) - 1) / (count - 1)) for i in range(count)]
    return [ordered[index] for index in indexes]


def representative_sources(sources: list[AudioSource], count: int) -> list[AudioSource]:
    if count == 0 or count >= len(sources):
        return sorted(sources, key=lambda item: str(item.path))
    rates: dict[int, list[AudioSource]] = {}
    for source in sources:
        rates.setdefault(source.sample_rate, []).append(source)
    if count < len(rates):
        return quantile_pick(sources, count)

    quotas = {rate: max(1, round(count * len(group) / len(sources))) for rate, group in rates.items()}
    while sum(quotas.values()) > count:
        candidates = [rate for rate, quota in quotas.items() if quota > 1]
        quotas[max(candidates, key=lambda rate: quotas[rate])] -= 1
    while sum(quotas.values()) < count:
        rate = max(rates, key=lambda key: len(rates[key]) - quotas[key])
        quotas[rate] += 1

    picked: list[AudioSource] = []
    for rate in sorted(rates):
        picked.extend(quantile_pick(rates[rate], min(quotas[rate], len(rates[rate]))))
    return sorted(picked, key=lambda item: (item.sample_rate, item.duration_seconds, str(item.path)))


def representative_voiceprint_sources(
    sources: list[AudioSource], count: int
) -> list[AudioSource]:
    enrollment_capable = [source for source in sources if source.duration_seconds >= 3.0]
    if not enrollment_capable:
        raise StressFailure("voiceprint requires an enrollment source of at least 3 seconds")
    return representative_sources(enrollment_capable, count)


def corpus_root_for_mode(data_dir: Path, mode: str) -> Path:
    if mode == "voiceprint-fallback":
        return VOICEPRINT_FALLBACK_FIXTURES
    return data_dir


def select_target_speaker_manifest_sources(
    corpus_root: Path, sources: list[AudioSource], manifest_path: Path
) -> tuple[list[AudioSource], int]:
    root = corpus_root.expanduser().resolve()
    try:
        manifest = json.loads(manifest_path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StressFailure(f"cannot read target-speaker manifest: {error}") from error
    items = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(items, list):
        raise StressFailure("target-speaker manifest must contain a files array")
    source_by_path = {source.path.resolve(): source for source in sources}
    enrollment: list[AudioSource] = []
    cases: list[tuple[str, AudioSource]] = []
    for item in items:
        if not isinstance(item, dict) or item.get("role") not in {"enrollment", "case"}:
            continue
        relative = item.get("path")
        if not isinstance(relative, str):
            raise StressFailure("target-speaker manifest entries require paths")
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as error:
            raise StressFailure(f"target-speaker manifest path escapes data directory: {relative}") from error
        source = source_by_path.get(path)
        if source is None:
            raise StressFailure(f"target-speaker manifest WAV is missing or invalid: {relative}")
        if item["role"] == "enrollment":
            enrollment.append(source)
        else:
            case_id = item.get("case_id")
            if not isinstance(case_id, str) or not case_id:
                raise StressFailure(f"target-speaker case is missing case_id: {relative}")
            cases.append((case_id, source))
    if not enrollment or not cases:
        raise StressFailure("target-speaker manifest requires enrollment and case WAVs")
    cases.sort(key=lambda item: item[0])
    return enrollment + [source for _, source in cases], len(enrollment)


def target_speaker_manifest_finish_recovery_sources(
    manifest_path: Path | None,
) -> set[str]:
    if manifest_path is None:
        return set()
    try:
        manifest = json.loads(manifest_path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    items = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(items, list):
        return set()
    return {
        item["path"]
        for item in items
        if isinstance(item, dict)
        and item.get("role") == "case"
        and isinstance(item.get("path"), str)
        and item.get("allow_finish_recovery") is True
    }


def target_speaker_content_verdict(
    cycles: list[dict[str, str]],
    mapping: list[dict[str, object]],
    manifest_path: Path | None,
) -> dict[str, object]:
    if manifest_path is None:
        return {"status": "FAIL", "reason": "speaker-turn accuracy requires a manifest", "cases": []}
    try:
        manifest = json.loads(manifest_path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {"status": "FAIL", "reason": f"cannot read role manifest: {error}", "cases": []}
    items = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(items, list):
        return {"status": "FAIL", "reason": "manifest is missing files", "cases": []}
    by_source = {
        item["path"]: item for item in items
        if isinstance(item, dict) and item.get("role") == "case" and isinstance(item.get("path"), str)
    }
    business_assertion = manifest.get("business_assertion", {})
    if not isinstance(business_assertion, dict):
        business_assertion = {}
    source_by_id = {
        str(item.get("id")): str(item.get("source"))
        for item in mapping if "id" in item and "source" in item
    }
    results: list[dict[str, object]] = []
    observed: set[str] = set()
    for cycle in cycles:
        source = source_by_id.get(cycle.get("id", ""), "")
        assertion = by_source.get(source)
        if assertion is None:
            continue
        case_id = str(assertion.get("case_id", ""))
        observed.add(case_id)
        try:
            text = bytes.fromhex(cycle.get("resultHex", "")).decode("utf-16-be")
            decode_error = ""
        except (UnicodeDecodeError, ValueError) as error:
            text, decode_error = "", str(error)
        required = assertion.get("required_texts", [])
        forbidden = assertion.get("forbidden_texts", [])
        if not forbidden and isinstance(business_assertion.get("forbidden_text"), str):
            forbidden = [business_assertion["forbidden_text"]]
        if not isinstance(required, list) or not required or not all(isinstance(v, str) and v for v in required):
            required = []
        if not isinstance(forbidden, list) or not forbidden or not all(isinstance(v, str) and v for v in forbidden):
            forbidden = []
        expected_count = assertion.get("expected_nonempty_public_finals")
        try:
            observed_count = int(cycle.get("nonEmptyFinals", "-1"))
        except ValueError:
            observed_count = -1
        passed = (
            not decode_error and bool(required) and bool(forbidden)
            and all(value in text for value in required)
            and all(value not in text for value in forbidden)
            and isinstance(expected_count, int) and observed_count == expected_count
        )
        results.append({
            "case_id": case_id, "source": source, "status": "PASS" if passed else "FAIL",
            "text": text, "required_texts": required, "forbidden_texts": forbidden,
            "expected_nonempty_public_finals": expected_count,
            "observed_nonempty_public_finals": observed_count, "decode_error": decode_error,
        })
    expected = {str(item.get("case_id", "")) for item in by_source.values()}
    passed = bool(results) and observed == expected and all(item["status"] == "PASS" for item in results)
    return {"status": "PASS" if passed else "FAIL", "expected_case_ids": sorted(expected),
            "observed_case_ids": sorted(observed), "cases": results}


def normalized_asr_text(value: str) -> str:
    return "".join(character.lower() for character in value if character.isalnum())


def expected_tail_verdict(
    cycles: list[dict[str, str]],
    mapping: list[dict[str, object]],
    manifest_path: Path | None,
) -> dict[str, object]:
    if manifest_path is None:
        return {"status": "NOT_APPLICABLE", "reason": "tail assertion disabled", "cases": []}
    try:
        manifest_bytes = manifest_path.expanduser().resolve().read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return {"status": "FAIL", "reason": f"cannot read tail manifest: {error}", "cases": []}
    items = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(items, list):
        return {"status": "FAIL", "reason": "tail manifest must contain a files array", "cases": []}

    expected_by_hash: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        source_hash = item.get("sha256")
        required_suffix = item.get("required_suffix")
        if not isinstance(source_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", source_hash):
            return {"status": "FAIL", "reason": "tail manifest contains an invalid sha256", "cases": []}
        if not isinstance(required_suffix, str) or not normalized_asr_text(required_suffix):
            return {"status": "FAIL", "reason": "tail manifest contains an empty suffix", "cases": []}
        if source_hash in expected_by_hash:
            return {"status": "FAIL", "reason": "tail manifest contains a duplicate sha256", "cases": []}
        expected_by_hash[source_hash] = normalized_asr_text(required_suffix)

    mapping_by_id = {str(item.get("id")): item for item in mapping}
    results: list[dict[str, object]] = []
    observed_hashes: set[str] = set()
    for cycle in cycles:
        source = mapping_by_id.get(cycle.get("id", ""), {})
        source_hash = source.get("source_sha256")
        if not isinstance(source_hash, str) or source_hash not in expected_by_hash:
            continue
        observed_hashes.add(source_hash)
        try:
            text = bytes.fromhex(cycle.get("resultHex", "")).decode("utf-16-be")
            decode_error = ""
        except (UnicodeDecodeError, ValueError) as error:
            text, decode_error = "", str(error)
        normalized = normalized_asr_text(text)
        required_suffix = expected_by_hash[source_hash]
        passed = not decode_error and normalized.endswith(required_suffix)
        results.append({
            "source_sha256": source_hash,
            "status": "PASS" if passed else "FAIL",
            "required_suffix_sha256": hashlib.sha256(required_suffix.encode("utf-8")).hexdigest(),
            "normalized_result_length": len(normalized),
            "decode_error": decode_error,
        })
    passed = (
        bool(expected_by_hash)
        and observed_hashes == set(expected_by_hash)
        and all(item["status"] == "PASS" for item in results)
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "expected_sha256": sorted(expected_by_hash),
        "observed_sha256": sorted(observed_hashes),
        "cases": results,
    }


def initial_signal_level(source: AudioSource, seconds: float = 3.0) -> float:
    with wave.open(str(source.path), "rb") as wav:
        raw = wav.readframes(min(wav.getnframes(), round(wav.getframerate() * seconds)))
    if not raw:
        return 0.0
    full_scale = float((1 << (source.sample_width * 8 - 1)) - 1)
    return audioop.rms(raw, source.sample_width) / full_scale


def convert_to_pcm(source: AudioSource, destination: Path) -> int:
    if source.sample_width != 2:
        raise StressFailure(f"unsupported sample width {source.sample_width * 8} for {source.path}")
    if source.channels not in (1, 2):
        raise StressFailure(f"unsupported channel count {source.channels} for {source.path}")
    with wave.open(str(source.path), "rb") as wav:
        raw = wav.readframes(wav.getnframes())
    if source.channels == 2:
        raw = audioop.tomono(raw, 2, 0.5, 0.5)
    if source.sample_rate != 16000:
        raw, _ = audioop.ratecv(raw, 2, 1, source.sample_rate, 16000, None)
    if len(raw) % 2:
        raw = raw[:-1]
    destination.write_bytes(raw)
    return len(raw)


def prepare_payload(
    sources: list[AudioSource], payload: Path, remote_dir: str, corpus_root: Path
) -> list[dict[str, object]]:
    audio_dir = payload / "audio"
    audio_dir.mkdir(parents=True)
    manifest_lines: list[str] = []
    mapping: list[dict[str, object]] = []
    for index, source in enumerate(sources):
        corpus_id = f"{index:06d}"
        filename = f"{corpus_id}.pcm"
        pcm_path = audio_dir / filename
        output_bytes = convert_to_pcm(source, pcm_path)
        manifest_lines.append(f"{corpus_id}\t{remote_dir}/audio/{filename}")
        mapping.append(
            {
                "id": corpus_id,
                "source": str(source.path.relative_to(corpus_root)),
                "source_sha256": sha256_file(source.path),
                "sample_rate": source.sample_rate,
                "channels": source.channels,
                "sample_width": source.sample_width,
                "duration_seconds": round(source.duration_seconds, 6),
                "pcm_bytes": output_bytes,
                "pcm_sha256": sha256_file(pcm_path),
            }
        )
    (payload / "manifest.txt").write_text("\n".join(manifest_lines) + "\n", encoding="ascii")
    (payload / "corpus.json").write_text(json.dumps(mapping, ensure_ascii=True, indent=2) + "\n")
    return mapping


def parse_status(text: str, elapsed: float, pid: int) -> MemorySample | None:
    values: dict[str, int] = {}
    for line in text.replace("\r", "").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        token = value.strip().split()[0] if value.strip() else ""
        if token.isdigit():
            values[key] = int(token)
    required = ("VmRSS", "VmHWM", "VmData", "VmSwap", "Threads")
    if not all(key in values for key in required):
        return None
    return MemorySample(
        elapsed_seconds=round(elapsed, 3),
        pid=pid,
        vm_rss_kb=values["VmRSS"],
        vm_hwm_kb=values["VmHWM"],
        vm_data_kb=values["VmData"],
        vm_swap_kb=values["VmSwap"],
        threads=values["Threads"],
    )


def read_process_sample(hdc: Hdc, started_at: float) -> MemorySample | None:
    pid_result = hdc.shell("pidof", BUNDLE, check=False)
    pid_tokens = pid_result.stdout.replace("\r", "").strip().split()
    if not pid_tokens or not pid_tokens[0].isdigit():
        return None
    pid = int(pid_tokens[0])
    status = hdc.shell("cat", f"/proc/{pid}/status", check=False)
    if status.returncode != 0:
        return None
    sample = parse_status(status.stdout, time.monotonic() - started_at, pid)
    if sample is None:
        return None
    process_stat = hdc.shell("cat", f"/proc/{pid}/stat", check=False)
    system_stat = hdc.shell("cat", "/proc/stat", check=False)
    if process_stat.returncode == 0 and system_stat.returncode == 0:
        process_ticks = parse_process_cpu_ticks(process_stat.stdout)
        system_cpu = parse_system_cpu_ticks(system_stat.stdout)
        if process_ticks is not None and system_cpu is not None:
            sample.process_cpu_ticks = process_ticks
            sample.system_cpu_ticks = system_cpu[0]
            sample.logical_cpus = system_cpu[1]
    return sample


def parse_process_cpu_ticks(text: str) -> int | None:
    closing_paren = text.rfind(")")
    if closing_paren < 0:
        return None
    fields = text[closing_paren + 1 :].strip().split()
    # The first field after comm is process state (field 3); utime/stime are fields 14/15.
    if len(fields) <= 12:
        return None
    try:
        return int(fields[11]) + int(fields[12])
    except ValueError:
        return None


def parse_system_cpu_ticks(text: str) -> tuple[int, int] | None:
    lines = text.replace("\r", "").splitlines()
    if not lines:
        return None
    aggregate = lines[0].split()
    if not aggregate or aggregate[0] != "cpu":
        return None
    try:
        counters = [int(value) for value in aggregate[1:]]
    except ValueError:
        return None
    # Linux reports guest/guest_nice as fields 9/10, but those ticks are already
    # included in user/nice. Counting them again would inflate the denominator
    # and under-report the application CPU percentage.
    total_ticks = sum(counters[:8])
    logical_cpus = sum(
        1 for line in lines[1:] if line.split() and line.split()[0][3:].isdigit()
        and line.split()[0].startswith("cpu")
    )
    return (total_ticks, logical_cpus) if total_ticks >= 0 and logical_cpus > 0 else None


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def cpu_statistics(samples: list[MemorySample]) -> dict[str, object]:
    valid = [
        sample
        for sample in samples
        if sample.process_cpu_ticks >= 0 and sample.system_cpu_ticks >= 0 and sample.logical_cpus > 0
    ]
    intervals: list[float] = []
    for previous, current in zip(valid, valid[1:]):
        if previous.pid != current.pid or previous.logical_cpus != current.logical_cpus:
            continue
        process_delta = current.process_cpu_ticks - previous.process_cpu_ticks
        system_delta = current.system_cpu_ticks - previous.system_cpu_ticks
        if process_delta < 0 or system_delta <= 0:
            continue
        intervals.append(process_delta / system_delta * current.logical_cpus * 100.0)
    if len(valid) < 2 or not intervals:
        return {
            "status": "INCONCLUSIVE",
            "reason": "fewer than two comparable CPU samples",
            "sample_count": len(valid),
        }
    first = valid[0]
    last = valid[-1]
    process_delta = last.process_cpu_ticks - first.process_cpu_ticks
    system_delta = last.system_cpu_ticks - first.system_cpu_ticks
    if process_delta < 0 or system_delta <= 0 or first.pid != last.pid:
        return {
            "status": "INCONCLUSIVE",
            "reason": "CPU counters were not monotonic for one process",
            "sample_count": len(valid),
        }
    logical_cpus = last.logical_cpus
    mean_single_core = process_delta / system_delta * logical_cpus * 100.0
    return {
        "status": "MEASURED",
        "sample_count": len(valid),
        "interval_count": len(intervals),
        "observation_seconds": round(last.elapsed_seconds - first.elapsed_seconds, 3),
        "logical_cpus": logical_cpus,
        "mean_single_core_equivalent_percent": round(mean_single_core, 3),
        "p50_single_core_equivalent_percent": round(percentile(intervals, 0.50), 3),
        "p95_single_core_equivalent_percent": round(percentile(intervals, 0.95), 3),
        "peak_single_core_equivalent_percent": round(max(intervals), 3),
        "mean_device_capacity_percent": round(mean_single_core / logical_cpus, 3),
        "p50_device_capacity_percent": round(percentile(intervals, 0.50) / logical_cpus, 3),
        "p95_device_capacity_percent": round(percentile(intervals, 0.95) / logical_cpus, 3),
        "peak_device_capacity_percent": round(max(intervals) / logical_cpus, 3),
    }


def parse_result(path: Path, run_id: str) -> tuple[dict[str, str], list[dict[str, str]]] | None:
    try:
        text = path.read_text(encoding="ascii")
    except (OSError, UnicodeError):
        return None
    summary: dict[str, str] | None = None
    cycles: list[dict[str, str]] = []
    for line in text.splitlines():
        parts = line.split("|")
        if not parts:
            continue
        fields = {key: value for key, _, value in (part.partition("=") for part in parts[1:]) if key}
        if parts[0] == "CYCLE":
            cycles.append(fields)
        elif parts[0] == "SUMMARY" and fields.get("runId") == run_id:
            summary = fields
    return (summary, cycles) if summary is not None else None


def terminal_callback_order_ok(trace: str) -> bool:
    callbacks = trace.split(">") if trace else []
    last_indexes = [index for index, item in enumerate(callbacks) if item.endswith(":final-last")]
    complete_indexes = [index for index, item in enumerate(callbacks) if item.endswith(":complete")]
    if len(last_indexes) != 1 or len(complete_indexes) != 1:
        return False
    last_index = last_indexes[0]
    complete_index = complete_indexes[0]
    if last_index > complete_index:
        return False
    session_prefix = callbacks[last_index].removesuffix("final-last")
    for item in callbacks[complete_index + 1:]:
        if item.startswith(session_prefix):
            return False
    return True


def median_window(values: list[int], from_start: bool) -> float:
    width = max(2, math.ceil(len(values) * 0.2))
    window = values[:width] if from_start else values[-width:]
    return statistics.median(window)


def memory_verdict(samples: list[MemorySample], max_growth_mb: float, max_thread_growth: int) -> dict[str, object]:
    if len(samples) < MIN_MEMORY_SAMPLES:
        return {
            "status": "INCONCLUSIVE",
            "reason": f"fewer than {MIN_MEMORY_SAMPLES} process samples",
            "sample_count": len(samples),
        }
    observation_seconds = samples[-1].elapsed_seconds - samples[0].elapsed_seconds
    if observation_seconds < MIN_MEMORY_OBSERVATION_SECONDS:
        return {
            "status": "INCONCLUSIVE",
            "reason": f"observation shorter than {MIN_MEMORY_OBSERVATION_SECONDS:.0f}s",
            "sample_count": len(samples),
            "observation_seconds": round(observation_seconds, 3),
        }
    warmup = max(1, len(samples) // 5)
    stable = samples[warmup:]
    rss = [sample.vm_rss_kb for sample in stable]
    data = [sample.vm_data_kb for sample in stable]
    threads = [sample.threads for sample in stable]
    elapsed = [sample.elapsed_seconds for sample in stable]
    head_rss = median_window(rss, True)
    tail_rss = median_window(rss, False)
    growth_mb = (tail_rss - head_rss) / 1024.0
    head_data = median_window(data, True)
    tail_data = median_window(data, False)
    head_threads = median_window(threads, True)
    tail_threads = median_window(threads, False)
    thread_growth = tail_threads - head_threads
    mean_elapsed = statistics.mean(elapsed)
    mean_rss = statistics.mean(rss)
    slope_denominator = sum((value - mean_elapsed) ** 2 for value in elapsed)
    rss_slope_mb_per_minute: float | None = None
    if observation_seconds >= MIN_MEMORY_SLOPE_SECONDS and slope_denominator > 0:
        rss_slope_kb_per_second = sum(
            (x - mean_elapsed) * (y - mean_rss) for x, y in zip(elapsed, rss)
        ) / slope_denominator
        rss_slope_mb_per_minute = rss_slope_kb_per_second * 60.0 / 1024.0
    third_medians: list[float] = []
    for index in range(3):
        start = round(index * len(rss) / 3)
        end = round((index + 1) * len(rss) / 3)
        third_medians.append(round(statistics.median(rss[start:end]) / 1024.0, 3))
    status = "PASS" if growth_mb <= max_growth_mb and thread_growth <= max_thread_growth else "FAIL"
    return {
        "status": status,
        "sample_count": len(samples),
        "observation_seconds": round(observation_seconds, 3),
        "warmup_samples_excluded": warmup,
        "head_rss_mb": round(head_rss / 1024.0, 3),
        "tail_rss_mb": round(tail_rss / 1024.0, 3),
        "rss_growth_mb": round(growth_mb, 3),
        "rss_slope_mb_per_minute": (
            round(rss_slope_mb_per_minute, 3) if rss_slope_mb_per_minute is not None else None
        ),
        "rss_third_medians_mb": third_medians,
        "peak_rss_mb": round(max(sample.vm_rss_kb for sample in samples) / 1024.0, 3),
        "peak_hwm_mb": round(max(sample.vm_hwm_kb for sample in samples) / 1024.0, 3),
        "head_vm_data_mb": round(head_data / 1024.0, 3),
        "tail_vm_data_mb": round(tail_data / 1024.0, 3),
        "vm_data_growth_mb": round((tail_data - head_data) / 1024.0, 3),
        "peak_swap_mb": round(max(sample.vm_swap_kb for sample in samples) / 1024.0, 3),
        "head_threads": head_threads,
        "tail_threads": tail_threads,
        "thread_growth": thread_growth,
        "max_rss_growth_mb": max_growth_mb,
        "max_thread_growth": max_thread_growth,
    }


def write_samples(path: Path, samples: Iterable[MemorySample]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(MemorySample.__annotations__))
        writer.writeheader()
        for sample in samples:
            writer.writerow(asdict(sample))


def target_speaker_realtime_verdict(hilog_path: Path, required: bool) -> dict[str, object]:
    pattern = re.compile(
        r"TARGET_SPEAKER_ENHANCEMENT\|processingMs=(\d+)\|queued=(\d+)\|maxQueued=(\d+)"
    )
    records = [
        tuple(int(value) for value in match.groups())
        for match in pattern.finditer(hilog_path.read_text(encoding="utf-8", errors="replace"))
    ]
    if not records:
        return {
            "status": "FAIL" if required else "NOT_APPLICABLE",
            "reason": "no target-speaker processing metrics observed" if required else "mode disabled",
            "chunk_count": 0,
        }
    processing = sorted(record[0] for record in records)
    p95_index = min(len(processing) - 1, math.ceil(len(processing) * 0.95) - 1)
    maximum_processing_ms = max(processing)
    maximum_queued_chunks = max(record[2] for record in records)
    # After the first 2 s window, a new chunk arrives every 1.75 s. A final short chunk may briefly
    # coexist with the last full chunk, so a depth of two is bounded and does not indicate drift.
    keeps_up = maximum_processing_ms < 1750 and maximum_queued_chunks <= 2
    status = ("PASS" if keeps_up else "FAIL") if required else "OBSERVED"
    return {
        "status": status,
        "chunk_count": len(records),
        "maximum_processing_ms": maximum_processing_ms,
        "p95_processing_ms": processing[p95_index],
        "maximum_queued_chunks": maximum_queued_chunks,
        "steady_state_chunk_interval_ms": 1750,
    }


def speaker_turn_final_latency_verdict(
    hilog_path: Path,
    required: bool,
    maximum_endpoint_latency_ms: int = 1000,
    maximum_finish_latency_ms: int = 1200,
    cycles: list[dict[str, str]] | None = None,
    finish_recovery_entry_ids: set[str] | None = None,
) -> dict[str, object]:
    pattern = re.compile(r"kind=UTTERANCE[^\n]*endpointToFinalLatencyMs=(\d+)")
    latencies = sorted(
        int(match.group(1))
        for match in pattern.finditer(hilog_path.read_text(encoding="utf-8", errors="replace"))
    )
    finish_latencies: list[int] = []
    expected_finish_recoveries = 0
    if finish_recovery_entry_ids and cycles is not None:
        for cycle in cycles:
            if cycle.get("id") not in finish_recovery_entry_ids:
                continue
            if cycle.get("speechEndsBeforeFinish") != "0":
                continue
            expected_finish_recoveries += 1
            try:
                latency = int(cycle.get("finishToFirstNonEmptyResultMs", "-1"))
            except ValueError:
                latency = -1
            if latency >= 0:
                finish_latencies.append(latency)
    if expected_finish_recoveries != len(finish_latencies):
        return {
            "status": "FAIL" if required else "OBSERVED",
            "reason": "missing finish-to-final metrics",
            "utterance_count": len(latencies),
            "finish_recovery_count": len(finish_latencies),
        }
    if not latencies and not finish_latencies:
        return {
            "status": "FAIL" if required else "NOT_APPLICABLE",
            "reason": "no trigger-to-final metrics observed" if required else "mode disabled",
            "utterance_count": 0,
        }
    endpoint_p95 = -1
    if latencies:
        p95_index = min(len(latencies) - 1, math.ceil(len(latencies) * 0.95) - 1)
        endpoint_p95 = latencies[p95_index]
    finish_p95 = -1
    if finish_latencies:
        finish_latencies.sort()
        p95_index = min(
            len(finish_latencies) - 1, math.ceil(len(finish_latencies) * 0.95) - 1
        )
        finish_p95 = finish_latencies[p95_index]
    maximum_endpoint = max(latencies) if latencies else -1
    maximum_finish = max(finish_latencies) if finish_latencies else -1
    keeps_up = (
        maximum_endpoint <= maximum_endpoint_latency_ms
        and maximum_finish <= maximum_finish_latency_ms
    )
    result: dict[str, object] = {
        "status": ("PASS" if keeps_up else "FAIL") if required else "OBSERVED",
        "utterance_count": len(latencies),
        "finish_recovery_count": len(finish_latencies),
        "maximum_endpoint_latency_ms": maximum_endpoint_latency_ms,
        "maximum_finish_latency_ms": maximum_finish_latency_ms,
    }
    if latencies:
        result["p95_endpoint_to_final_ms"] = endpoint_p95
        result["maximum_endpoint_to_final_ms"] = maximum_endpoint
    if finish_latencies:
        result["p95_finish_to_final_ms"] = finish_p95
        result["maximum_finish_to_final_ms"] = maximum_finish
    return result


def build_install(device: str) -> None:
    command = [
        str(SCRIPT_DIR / "build_install_smoke.sh"),
        "--device",
        device,
        "--zh-en-only",
    ]
    result = run(command, check=False, capture=False)
    if result.returncode != 0:
        raise StressFailure("Harmony demo build/install smoke test failed")


def capture_hilog(hdc: Hdc, destination: Path) -> None:
    result = hdc.shell("hilog", "-x", check=False)
    destination.write_text(result.stdout + result.stderr, encoding="utf-8", errors="replace")


def run_stress(args: argparse.Namespace) -> Path:
    hdc_path = locate_hdc()
    device = select_target(hdc_path, args.device)
    hdc = Hdc(hdc_path, device)
    finish_recovery_sources = target_speaker_manifest_finish_recovery_sources(
        args.target_speaker_manifest
    )
    requested_corpus_root = args.data_dir.expanduser().resolve()
    corpus_root = corpus_root_for_mode(requested_corpus_root, args.mode)
    all_sources = inspect_wavs(corpus_root)
    voiceprint_representative_modes = {
        "voiceprint", "voiceprint-vad-begin", "voiceprint-vad-begin-idle",
        "speaker-vad-onstart", "cold-start-pcm-gap", "continuous-voiceprint-speaker-vad",
        "speaker-vad-shutdown-relicense",
    }
    selected = (
        representative_voiceprint_sources(all_sources, args.files)
        if args.mode in voiceprint_representative_modes
        else representative_sources(all_sources, args.files)
    )
    target_speaker_enrollment_count = 1
    if args.mode == "voiceprint-fallback":
        sources_by_name = {source.path.name: source for source in all_sources}
        required_names = ("000_enroll.wav", "001_recognize.wav")
        if any(name not in sources_by_name for name in required_names):
            raise StressFailure(
                "voiceprint-fallback requires 000_enroll.wav and 001_recognize.wav"
            )
        selected = [sources_by_name[name] for name in required_names]
    elif args.mode == "cold-start-pcm-gap":
        # This regression gate uses a 5 s vadBegin window and measures synchronous startListening
        # latency plus exact PCM delivery. Unlike the 1 s VAD gates, it does not require direct onset.
        selected = sorted(selected, key=lambda source: (-source.duration_seconds, str(source.path)))[:1]
    elif args.mode in ("voiceprint-vad-begin", "speaker-vad-onstart"):
        # The carrier adds 400 ms leading silence in half the cycles. Keep only sources whose own
        # first 200 ms already contain signal, leaving at least 400 ms for VAD/ASR confirmation
        # before the 1000 ms vadBegin boundary.
        # Otherwise the test would correctly time out before the source itself starts speaking.
        selected.sort(key=initial_signal_level, reverse=True)
        selected = [source for source in selected if initial_signal_level(source, 0.2) >= 0.015]
        # Runtime Speaker VAD rejects non-target speakers, so its enrollment and recognition source
        # must be identical. Verification-only mode can intentionally span several sources.
        selected = selected[:1] if args.mode == "speaker-vad-onstart" else selected[:8]
        if not selected:
            raise StressFailure(f"{args.mode} requires a source with a non-silent onset")
    elif args.mode == "voiceprint-vad-begin-idle":
        selected.sort(key=initial_signal_level, reverse=True)
        selected = selected[:1]
    elif args.mode in TARGET_SPEAKER_MODES:
        if args.target_speaker_manifest is not None:
            selected, target_speaker_enrollment_count = select_target_speaker_manifest_sources(
                args.data_dir, all_sources, args.target_speaker_manifest
            )
        else:
            selected = sorted(selected, key=lambda source: str(source.path))
        if len(selected) < 2:
            raise StressFailure(
                f"{args.mode} requires an enrollment WAV followed by at least one test WAV"
            )

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    entropy = hashlib.sha256(f"{time.time_ns()}-{args.mode}".encode()).hexdigest()[:8]
    run_id = f"{timestamp}-{args.mode}-{entropy}"
    artifact_dir = args.output_root.expanduser().resolve() / run_id
    payload = artifact_dir / "payload"
    payload.mkdir(parents=True)
    remote_dir = f"{REMOTE_ROOT}/{run_id}"
    mapping = prepare_payload(selected, payload, remote_dir, corpus_root)
    finish_recovery_entry_ids = {
        str(item["id"])
        for item in mapping
        if item.get("source") in finish_recovery_sources
    }
    remote_manifest = f"{remote_dir}/manifest.txt"
    remote_result = f"{remote_dir}/result.txt"
    local_result = artifact_dir / "result.txt"

    inventory = {
        "valid_wavs": len(all_sources),
        "selected_wavs": len(selected),
        "total_valid_duration_seconds": round(sum(item.duration_seconds for item in all_sources), 3),
        "selected_duration_seconds": round(sum(item.duration_seconds for item in selected), 3),
        "target_speaker_enrollment_wavs": target_speaker_enrollment_count,
        "sample_rates": {str(rate): sum(1 for item in all_sources if item.sample_rate == rate) for rate in sorted({item.sample_rate for item in all_sources})},
    }
    (artifact_dir / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")

    print(
        f"[INFO] corpus: {inventory['valid_wavs']} valid WAVs, "
        f"{inventory['total_valid_duration_seconds'] / 3600:.2f} h; selected {len(selected)} files"
    )
    installed_bundle: dict[str, object] | None = None
    if not args.skip_build_install and not args.installed_package:
        print("[INFO] building, installing, and smoke-testing the Harmony SDK test carrier")
        build_install(device)
    if args.installed_package:
        build_identity, installed_bundle = installed_package_identity(hdc)
        (artifact_dir / "installed-bundle.json").write_text(
            json.dumps(installed_bundle, ensure_ascii=True, indent=2) + "\n"
        )
    else:
        build_identity = verified_build_identity()

    print(f"[INFO] sending {sum(int(item['pcm_bytes']) for item in mapping) / 1024 / 1024:.1f} MiB PCM payload")
    hdc.app_send(payload, remote_dir)
    hdc.shell("hilog", "-r", check=False)
    hdc.shell("aa", "force-stop", BUNDLE, check=False)

    start_command = [
        "aa", "start", "-a", ABILITY, "-b", BUNDLE, "-m", MODULE,
        "--ps", "stress", "true",
        "--ps", "stressRunId", run_id,
        "--ps", "stressManifest", remote_manifest,
        "--ps", "stressResult", remote_result,
        "--ps", "stressMode", args.mode,
        "--ps", "stressCycles", str(args.cycles),
        "--ps", "stressSettleMs", str(args.settle_ms),
        "--ps", "stressPaceMs", str(args.pace_ms),
        "--ps", "stressEnrollmentCount", str(target_speaker_enrollment_count),
        "--ps", "stressEnforceTargetSpeakerBusinessText",
        # Manifest-driven assertions are evaluated per case after the device run.
        # The carrier's legacy C1-only text check must not reject another corpus.
        "false" if args.target_speaker_manifest is not None or args.skip_target_content_check else "true",
        "--ps", "stressSpeakerVadFinishRecoveryEntryIds",
        ",".join(sorted(finish_recovery_entry_ids)) or "none",
        "--ps", "stressSpeakerVadThreshold",
        str((args.speaker_vad_threshold if args.speaker_vad_threshold is not None else -2) + 2),
    ]
    start_result = hdc.shell(*start_command, check=False)
    start_output = (start_result.stdout + start_result.stderr).lower()
    if (
        start_result.returncode != 0
        or "error" in start_output
        or "invalid number of parameters" in start_output
    ):
        raise StressFailure(f"failed to start stress ability: {(start_result.stdout + start_result.stderr).strip()}")

    samples: list[MemorySample] = []
    started_at = time.monotonic()
    parsed: tuple[dict[str, str], list[dict[str, str]]] | None = None
    process_seen = False
    next_poll = started_at
    print(f"[INFO] running mode={args.mode} cycles={args.cycles}")
    while time.monotonic() - started_at < args.timeout:
        now = time.monotonic()
        if now < next_poll:
            time.sleep(min(0.1, next_poll - now))
            continue
        sample = read_process_sample(hdc, started_at)
        if sample is not None:
            process_seen = True
            samples.append(sample)
        elif process_seen:
            capture_hilog(hdc, artifact_dir / "hilog.txt")
            write_samples(artifact_dir / "memory.csv", samples)
            raise StressFailure("SDK test carrier exited before the stress summary was written")

        temporary_result = artifact_dir / "result.tmp"
        if hdc.app_recv(remote_result, temporary_result):
            candidate = parse_result(temporary_result, run_id)
            if candidate is not None:
                shutil.move(temporary_result, local_result)
                parsed = candidate
                break
        temporary_result.unlink(missing_ok=True)
        next_poll = time.monotonic() + args.sample_interval
    if parsed is None:
        capture_hilog(hdc, artifact_dir / "hilog.txt")
        write_samples(artifact_dir / "memory.csv", samples)
        raise StressFailure(f"timed out after {args.timeout}s waiting for the stress summary")

    workload_samples = list(samples)
    observe_until = time.monotonic() + args.post_run_observe
    while time.monotonic() < observe_until:
        sample = read_process_sample(hdc, started_at)
        if sample is not None:
            samples.append(sample)
        time.sleep(args.sample_interval)

    capture_hilog(hdc, artifact_dir / "hilog.txt")
    write_samples(artifact_dir / "memory.csv", samples)
    app_summary, cycle_results = parsed
    memory = memory_verdict(samples, args.max_rss_growth_mb, args.max_thread_growth)
    realtime_required = args.pace_ms >= 20
    if args.mode == "speaker-vad-turn":
        target_speaker_realtime = speaker_turn_final_latency_verdict(
            artifact_dir / "hilog.txt", realtime_required, cycles=cycle_results,
            finish_recovery_entry_ids=finish_recovery_entry_ids,
        )
    else:
        target_speaker_realtime = target_speaker_realtime_verdict(
            artifact_dir / "hilog.txt",
            realtime_required and args.mode == "target-speaker-enhancement",
        )
    if args.mode == "speaker-vad-turn" and not args.skip_target_content_check:
        target_speaker_content = target_speaker_content_verdict(
            cycle_results, mapping, args.target_speaker_manifest
        )
    else:
        target_speaker_content = {
            "status": "NOT_APPLICABLE",
            "reason": "accuracy gate disabled or mode is lifecycle-only",
            "cases": [],
        }
    expected_tail = expected_tail_verdict(
        cycle_results, mapping, args.expected_tail_manifest
    )
    cpu = cpu_statistics(workload_samples)
    completed = int(app_summary.get("completed", "0"))
    empty_finals = int(app_summary.get("emptyFinals", "0"))
    empty_rate = empty_finals / completed if completed else 1.0
    live_stream_counts: list[int] = []
    for cycle in cycle_results:
        try:
            live_stream_counts.append(int(cycle["liveStreams"]))
        except (KeyError, ValueError):
            continue
    nonzero_live_stream_cycles = sum(1 for count in live_stream_counts if count != 0)
    stream_status = "PASS" if len(live_stream_counts) == completed and nonzero_live_stream_cycles == 0 else "FAIL"
    empty_status = "PASS"
    if args.mode in FINISH_MODES and empty_rate > args.max_empty_final_rate:
        empty_status = "FAIL"

    overall = "PASS"
    failures: list[str] = []
    if app_summary.get("status") != "PASS":
        overall = "FAIL"
        failures.append("SDK contract checks failed")
    if memory.get("status") == "FAIL":
        overall = "FAIL"
        failures.append("RSS/thread growth exceeded threshold")
    elif args.mode == "continuous-long-session" and memory.get("status") != "PASS":
        overall = "FAIL"
        failures.append("continuous long-session memory verdict was inconclusive")
    if stream_status == "FAIL":
        overall = "FAIL"
        failures.append("native stream ownership check failed")
    if empty_status == "FAIL":
        overall = "FAIL"
        failures.append("empty-final rate exceeded threshold")
    if target_speaker_realtime.get("status") == "FAIL":
        overall = "FAIL"
        failures.append("target-speaker processing did not keep up with real-time input")
    if target_speaker_content.get("status") == "FAIL":
        overall = "FAIL"
        failures.append("target-speaker content accuracy assertion failed")
    if expected_tail.get("status") == "FAIL":
        overall = "FAIL"
        failures.append("expected ASR tail assertion failed")
    if args.mode in ("finish-shutdown-relicense", "speaker-vad-shutdown-relicense") and any(
        not terminal_callback_order_ok(cycle.get("trace", "")) for cycle in cycle_results
    ):
        overall = "FAIL"
        failures.append("terminal callback order check failed")
    if args.mode in ("finish-shutdown-relicense", "speaker-vad-shutdown-relicense") and any(
        cycle.get("recoveryStarts") != "1"
        or cycle.get("recoveryLastFinals") != "1"
        or cycle.get("recoveryCompletes") != "1"
        or cycle.get("recoveryErrors") != "0"
        or cycle.get("recoveryTerminalOrder") != "1"
        or cycle.get("recoveryUnexpectedCallbacks") != "0"
        for cycle in cycle_results
    ):
        overall = "FAIL"
        failures.append("Runtime recovery session check failed")

    report = {
        "run_id": run_id,
        "mode": args.mode,
        "overall_status": overall,
        "failures": failures,
        "device": device,
        "build_identity": build_identity,
        "configuration": {
            "cycles": args.cycles,
            "settle_ms": args.settle_ms,
            "pace_ms": args.pace_ms,
            "sample_interval_seconds": args.sample_interval,
            "post_run_observe_seconds": args.post_run_observe,
            "target_content_check_enabled": not args.skip_target_content_check,
            "speaker_vad_threshold": args.speaker_vad_threshold,
            "finish_recovery_entry_ids": sorted(finish_recovery_entry_ids),
        },
        "inventory": inventory,
        "application": app_summary,
        "empty_finals": {
            "status": empty_status,
            "count": empty_finals,
            "rate": round(empty_rate, 6),
            "max_rate": args.max_empty_final_rate,
        },
        "native_streams": {
            "status": stream_status,
            "observed_cycles": len(live_stream_counts),
            "nonzero_cycles": nonzero_live_stream_cycles,
            "max_live_streams": max(live_stream_counts, default=0),
        },
        "target_speaker_realtime": target_speaker_realtime,
        "target_speaker_content": target_speaker_content,
        "expected_tail": expected_tail,
        "memory": memory,
        "cpu": cpu,
        "cycles": cycle_results,
    }
    (artifact_dir / "report.json").write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n")
    print(
        f"[{overall}] sdk={app_summary.get('status')} memory={memory.get('status')} "
        f"emptyFinalRate={empty_rate:.3f} artifacts={artifact_dir}"
    )
    if "rss_growth_mb" in memory:
        slope = memory["rss_slope_mb_per_minute"]
        slope_text = f"{slope} MiB/min" if slope is not None else f"inconclusive (<{MIN_MEMORY_SLOPE_SECONDS:.0f}s)"
        print(
            f"[INFO] RSS head={memory['head_rss_mb']} MiB tail={memory['tail_rss_mb']} MiB "
            f"growth={memory['rss_growth_mb']} MiB peak={memory['peak_rss_mb']} MiB "
            f"slope={slope_text}"
        )
    if overall != "PASS":
        raise StressFailure("; ".join(failures))
    return artifact_dir


def main() -> int:
    try:
        run_stress(parse_args())
        return 0
    except (StressFailure, subprocess.SubprocessError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
