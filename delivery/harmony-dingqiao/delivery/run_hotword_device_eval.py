#!/usr/bin/env python3
"""Run the fixed, opt-in hotword A/B fixture on a connected Harmony device."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
PROJECT_ROOT = REPO_ROOT / "delivery" / "harmony-dingqiao"
DEFAULT_FIXTURE = SCRIPT_DIR / "fixtures" / "hotword_eval_400.jsonl"
BUNDLE = "com.amphion.asr.harmony.debug"
MODULE = "amphion_asr_demo"
ABILITY = "EntryAbility"
REMOTE_ROOT = "/data/storage/el2/base/files/asr-hotword-eval"


class EvalFailure(RuntimeError):
    pass


def command(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, encoding="utf-8", errors="replace",
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_fixture(path: Path) -> list[dict[str, object]]:
    checksum_path = path.with_suffix(path.suffix + ".sha256")
    if not path.is_file() or not checksum_path.is_file():
        raise EvalFailure(f"fixture or checksum missing: {path}")
    expected = checksum_path.read_text(encoding="ascii").split()[0]
    actual = sha256(path)
    if actual != expected:
        raise EvalFailure(f"fixture checksum mismatch: expected {expected}, got {actual}")
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not entries:
        raise EvalFailure("fixed fixture must not be empty")
    if [entry.get("fixture_index") for entry in entries] != list(range(len(entries))):
        raise EvalFailure("fixture indexes are not a contiguous fixed sequence")
    return entries


def locate_hdc() -> Path:
    root = Path(os.environ.get("DEVECO_STUDIO_HOME", "/Applications/DevEco-Studio.app/Contents"))
    path = root / "sdk" / "default" / "openharmony" / "toolchains" / "hdc"
    if not path.is_file():
        raise EvalFailure(f"HDC not found: {path}")
    return path


def select_device(hdc: Path, requested: str) -> str:
    if requested:
        return requested
    result = command([str(hdc), "list", "targets"])
    targets = [line.strip() for line in result.stdout.replace("\r", "").splitlines()
               if line.strip() and line.strip() != "[Empty]"]
    if len(targets) != 1:
        raise EvalFailure(f"expected one connected device, found {len(targets)}")
    return targets[0]


class Hdc:
    def __init__(self, executable: Path, target: str):
        self.executable = executable
        self.target = target

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return command([str(self.executable), "-t", self.target, *args], check=check)

    def shell(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return self.run("shell", *args, check=check)

    def send(self, local: Path, remote: str) -> None:
        result = self.run("file", "send", "-b", BUNDLE, str(local), remote, check=False)
        if result.returncode or "[Fail]" in result.stdout + result.stderr:
            raise EvalFailure(f"device send failed: {(result.stdout + result.stderr).strip()}")

    def recv(self, remote: str, local: Path) -> bool:
        local.unlink(missing_ok=True)
        result = self.run("file", "recv", "-b", BUNDLE, remote, str(local), check=False)
        return not result.returncode and "[Fail]" not in result.stdout + result.stderr and local.is_file()


def convert_to_pcm(source: Path, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    wav_path = destination.with_suffix(".tmp.wav")
    result = command(["/usr/bin/afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1",
                      str(source), str(wav_path)], check=False)
    if result.returncode:
        raise EvalFailure(f"afconvert failed for {source}: {(result.stdout + result.stderr).strip()}")
    try:
        data = wav_path.read_bytes()
        if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            raise EvalFailure(f"afconvert did not produce RIFF/WAVE for {source}")
        audio_format = channels = sample_rate = bits_per_sample = 0
        pcm: bytes | None = None
        offset = 12
        while offset + 8 <= len(data):
            chunk_id = data[offset:offset + 4]
            chunk_size = struct.unpack_from("<I", data, offset + 4)[0]
            chunk_start = offset + 8
            chunk_end = chunk_start + chunk_size
            if chunk_end > len(data):
                raise EvalFailure(f"truncated WAVE chunk for {source}")
            if chunk_id == b"fmt " and chunk_size >= 16:
                audio_format, channels, sample_rate = struct.unpack_from("<HHI", data, chunk_start)
                bits_per_sample = struct.unpack_from("<H", data, chunk_start + 14)[0]
            elif chunk_id == b"data":
                pcm = data[chunk_start:chunk_end]
            offset = chunk_end + (chunk_size & 1)
        if audio_format not in {1, 65534} or channels != 1 or sample_rate != 16000 or bits_per_sample != 16:
            raise EvalFailure(
                f"unexpected converted format for {source}: "
                f"format={audio_format} channels={channels} rate={sample_rate} bits={bits_per_sample}"
            )
        if pcm is None or not pcm:
            raise EvalFailure(f"converted WAVE has no PCM data: {source}")
        destination.write_bytes(pcm)
        return len(pcm)
    finally:
        wav_path.unlink(missing_ok=True)


def prepare_payload(entries: list[dict[str, object]], data_root: Path, payload: Path,
                    remote_dir: str) -> int:
    data_asr = data_root / "DATA_ASR"
    audio_dir = payload / "audio"
    audio_dir.mkdir(parents=True)
    manifest_lines: list[str] = []
    total_bytes = 0
    for index, entry in enumerate(entries):
        source = data_asr / str(entry["audio"])
        if not source.is_file():
            raise EvalFailure(f"fixture source missing: {source}")
        pcm = audio_dir / f"{index:03d}.pcm"
        total_bytes += convert_to_pcm(source, pcm)
        device_entry = {
            "id": str(entry["id"]),
            # Dingqiao's ZH_EN engine is selected with zh-CN and is itself bilingual.
            "language": "zh-CN",
            "path": f"{remote_dir}/audio/{index:03d}.pcm",
            "hotwords": entry["hotwords"],
        }
        manifest_lines.append(json.dumps(device_entry, ensure_ascii=False, separators=(",", ":")))
    (payload / "manifest.jsonl").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    return total_bytes


def build_install(device: str) -> None:
    result = subprocess.run([str(SCRIPT_DIR / "build_install_smoke.sh"), "--device", device,
                             "--zh-en-only"], text=True)
    if result.returncode:
        raise EvalFailure("Harmony carrier build/install failed")


def parse_complete_result(path: Path, expected_lines: int) -> list[dict[str, object]] | None:
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
        if len(lines) < expected_lines:
            return None
        rows = [json.loads(line) for line in lines]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if len(rows) != expected_lines:
        raise EvalFailure(f"device returned {len(rows)} rows, expected {expected_lines}")
    return rows


def normalize_zh(text: str) -> list[str]:
    return [char.casefold() for char in text if unicodedata.category(char)[0] in {"L", "N"}]


def normalize_en(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", text.casefold())


def units(text: str, language: str) -> list[str]:
    return normalize_zh(text) if language.startswith("zh") else normalize_en(text)


def edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for i, ref in enumerate(reference, 1):
        current = [i]
        for j, hyp in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (ref != hyp)))
        previous = current
    return previous[-1]


def hotword_hit(hypothesis: str, hotword: str, language: str) -> bool:
    target = units(hotword, language)
    observed = units(hypothesis, language)
    if not target:
        return False
    width = len(target)
    return any(observed[i:i + width] == target for i in range(len(observed) - width + 1))


def score(entries: list[dict[str, object]], device_rows: list[dict[str, object]],
          artifact_dir: Path, fixture_digest: str, variants_to_score: tuple[str, ...]) -> dict[str, object]:
    by_key = {(str(row["id"]), str(row["variant"])): row for row in device_rows}
    details: list[dict[str, object]] = []
    aggregates: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    stratum_aggregates: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for entry in entries:
        case_id = str(entry["id"])
        language = str(entry["language"])
        reference = str(entry["reference"])
        hotwords = [str(word) for word in entry["hotwords"]]
        reference_units = units(reference, language)
        case: dict[str, object] = dict(entry)
        variants: dict[str, dict[str, object]] = {}
        for variant in variants_to_score:
            row = by_key.get((case_id, variant))
            if row is None:
                raise EvalFailure(f"missing device result: {case_id}/{variant}")
            hypothesis = str(row.get("text", ""))
            errors = edit_distance(reference_units, units(hypothesis, language))
            hits = [hotword_hit(hypothesis, word, language) for word in hotwords]
            result = dict(row)
            result.update({"edit_errors": errors, "reference_units": len(reference_units),
                           "hotword_hits": hits, "all_hotwords_hit": all(hits)})
            variants[variant] = result
            group = f"{language}:{variant}"
            aggregates[group]["edit_errors"] += errors
            aggregates[group]["reference_units"] += len(reference_units)
            aggregates[group]["hotwords"] += len(hits)
            aggregates[group]["hotword_hits"] += sum(hits)
            aggregates[group]["cases"] += 1
            aggregates[group]["all_hit_cases"] += int(all(hits))
            aggregates[group]["device_errors"] += int(int(row.get("error_code", 0)) != 0)
            stratum_group = f"{entry['stratum']}:{variant}"
            stratum_aggregates[stratum_group]["edit_errors"] += errors
            stratum_aggregates[stratum_group]["reference_units"] += len(reference_units)
            stratum_aggregates[stratum_group]["hotwords"] += len(hits)
            stratum_aggregates[stratum_group]["hotword_hits"] += sum(hits)
            stratum_aggregates[stratum_group]["cases"] += 1
            stratum_aggregates[stratum_group]["all_hit_cases"] += int(all(hits))
            stratum_aggregates[stratum_group]["device_errors"] += int(int(row.get("error_code", 0)) != 0)
        case["variants"] = variants
        if "baseline" in variants and "hotword" in variants:
            baseline_errors = int(variants["baseline"]["edit_errors"])
            hotword_errors = int(variants["hotword"]["edit_errors"])
            case["delta_edit_errors"] = hotword_errors - baseline_errors
            case["classification"] = ("improved" if hotword_errors < baseline_errors else
                                      "regressed" if hotword_errors > baseline_errors else "unchanged")
        details.append(case)

    def summarize(source: dict[str, dict[str, float]]) -> dict[str, object]:
        summary: dict[str, object] = {}
        for group, values in sorted(source.items()):
            summary[group] = {
                "cases": int(values["cases"]),
                "error_rate": values["edit_errors"] / max(1, values["reference_units"]),
                "hotword_recall": values["hotword_hits"] / max(1, values["hotwords"]),
                "all_hotwords_hit_rate": values["all_hit_cases"] / max(1, values["cases"]),
                "device_errors": int(values["device_errors"]),
            }
        return summary

    summary_groups = summarize(aggregates)
    summary_strata = summarize(stratum_aggregates)
    counts = defaultdict(int)
    for item in details:
        if "classification" in item:
            counts[str(item["classification"])] += 1
    report = {
        "fixture_sha256": fixture_digest,
        "case_count": len(entries),
        "comparison": dict(counts),
        "groups": summary_groups,
        "strata": summary_strata,
    }
    (artifact_dir / "details.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in details), encoding="utf-8")
    (artifact_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Harmony hotword device evaluation", "", f"Fixed cases: {len(entries)}",
             f"Fixture SHA-256: `{report['fixture_sha256']}`", "",
             "| Language / variant | Error rate | Hotword recall | All-hotword case rate | Device errors |",
             "|---|---:|---:|---:|---:|"]
    for group, values in summary_groups.items():
        assert isinstance(values, dict)
        lines.append(f"| {group} | {values['error_rate']:.2%} | {values['hotword_recall']:.2%} | "
                     f"{values['all_hotwords_hit_rate']:.2%} | {values['device_errors']} |")
    lines.extend(["", "## Strata", "",
                  "| Stratum / variant | Error rate | Hotword recall | All-hotword case rate |",
                  "|---|---:|---:|---:|"])
    for group, values in summary_strata.items():
        assert isinstance(values, dict)
        lines.append(f"| {group} | {values['error_rate']:.2%} | {values['hotword_recall']:.2%} | "
                     f"{values['all_hotwords_hit_rate']:.2%} |")
    lines.extend(["", f"Improved: {counts['improved']}; unchanged: {counts['unchanged']}; "
                  f"regressed: {counts['regressed']}.", ""])
    (artifact_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True,
                        help="Extracted local bundle root containing DATA_ASR.")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--device", default="")
    parser.add_argument("--skip-build-install", action="store_true")
    parser.add_argument("--police-enhancement", choices=("on", "off"), default="off",
                        help="Enable the final police/LAC pipeline for every recognition.")
    parser.add_argument("--hotword-only", action="store_true",
                        help="Skip the no-hotword baseline (useful for paired multi-build runs).")
    parser.add_argument("--pace-ms", type=int, default=0)
    parser.add_argument("--max-cases", type=int, default=0,
                        help="Debug only; 0 runs all fixed cases.")
    parser.add_argument("--start-index", type=int, default=0,
                        help="Debug/recovery only; begin at this fixed fixture index.")
    parser.add_argument("--timeout", type=int, default=10800)
    parser.add_argument("--output-root", type=Path,
                        default=PROJECT_ROOT / "build" / "hotword-device-eval")
    args = parser.parse_args()
    if args.pace_ms < 0 or args.max_cases < 0 or args.start_index < 0 or args.timeout <= 0:
        parser.error("timing/count values must be non-negative and timeout must be positive")
    return args


def main() -> int:
    args = parse_args()
    entries = verify_fixture(args.fixture.resolve())
    entries = entries[args.start_index:]
    if args.max_cases:
        entries = entries[:args.max_cases]
    data_root = args.data_root.expanduser().resolve()
    if not (data_root / "DATA_ASR").is_dir():
        raise EvalFailure(f"DATA_ASR missing below {data_root}")
    hdc_path = locate_hdc()
    device = select_device(hdc_path, args.device)
    hdc = Hdc(hdc_path, device)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    artifact_dir = args.output_root.resolve() / run_id
    payload = artifact_dir / "payload"
    payload.mkdir(parents=True)
    remote_dir = f"{REMOTE_ROOT}/{run_id}"
    print(f"[INFO] preparing {len(entries)} fixed cases; fixture={sha256(args.fixture.resolve())}")
    total_bytes = prepare_payload(entries, data_root, payload, remote_dir)
    print(f"[INFO] prepared {total_bytes / 1024 / 1024:.1f} MiB PCM")
    if not args.skip_build_install:
        print("[INFO] building and installing the opt-in test carrier")
        build_install(device)
    hdc.send(payload, remote_dir)
    remote_manifest = f"{remote_dir}/manifest.jsonl"
    remote_result = f"{remote_dir}/result.jsonl"
    hdc.shell("hilog", "-r", check=False)
    hdc.shell("aa", "force-stop", BUNDLE, check=False)
    started = hdc.shell(
        "aa", "start", "-a", ABILITY, "-b", BUNDLE, "-m", MODULE,
        "--ps", "hotwordEval", "true",
        "--ps", "hotwordEvalManifest", remote_manifest,
        "--ps", "hotwordEvalResult", remote_result,
        "--ps", "hotwordEvalPaceMs", str(args.pace_ms),
        "--ps", "hotwordEvalMaxCases", str(args.max_cases),
        "--ps", "hotwordEvalPoliceEnhancement", str(args.police_enhancement == "on").lower(),
        "--ps", "hotwordEvalHotwordOnly", str(args.hotword_only).lower(),
        check=False)
    if started.returncode or "error" in (started.stdout + started.stderr).casefold():
        raise EvalFailure(f"failed to start eval carrier: {(started.stdout + started.stderr).strip()}")

    expected_lines = len(entries) * (1 if args.hotword_only else 2)
    result_rows: list[dict[str, object]] | None = None
    deadline = time.monotonic() + args.timeout
    temporary = artifact_dir / "device-result.tmp"
    last_count = -1
    while time.monotonic() < deadline:
        if hdc.recv(remote_result, temporary):
            try:
                count = len([line for line in temporary.read_text(encoding="utf-8").splitlines() if line])
            except (OSError, UnicodeDecodeError):
                count = 0
            if count != last_count:
                print(f"[INFO] device progress {count}/{expected_lines} recognitions")
                last_count = count
            result_rows = parse_complete_result(temporary, expected_lines)
            if result_rows is not None:
                break
        time.sleep(2)
    if result_rows is None:
        hilog = hdc.shell("hilog", "-x", check=False)
        (artifact_dir / "hilog.txt").write_text(hilog.stdout + hilog.stderr, encoding="utf-8")
        raise EvalFailure(f"timed out after {args.timeout}s ({last_count}/{expected_lines} rows)")
    shutil.move(temporary, artifact_dir / "device-result.jsonl")
    hilog = hdc.shell("hilog", "-x", check=False)
    (artifact_dir / "hilog.txt").write_text(hilog.stdout + hilog.stderr, encoding="utf-8")
    variants_to_score = ("hotword",) if args.hotword_only else ("baseline", "hotword")
    report = score(entries, result_rows, artifact_dir, sha256(args.fixture.resolve()), variants_to_score)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    device_errors = sum(
        int(values["device_errors"])
        for values in report["groups"].values()
        if isinstance(values, dict)
    )
    if device_errors:
        raise EvalFailure(f"device evaluation completed with {device_errors} recognition errors")
    print(f"[PASS] report: {artifact_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EvalFailure as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        raise SystemExit(1)
