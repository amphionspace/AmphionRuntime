#!/usr/bin/env python3
"""Pull, validate, redact, and package Harmony ASR diagnostics."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile


BUNDLE = "com.amphion.asr.harmony.demo"
REMOTE_ROOT = "/data/storage/el2/base/files/asr-diagnostics"
FORBIDDEN_KEYS = {
    "license",
    "licenseText",
    "privateKey",
    "deviceSerial",
    "voiceprintId",
    "voiceprintIds",
    "hotwords",
}


def locate_hdc() -> Path:
    deveco = Path(os.environ.get("DEVECO_STUDIO_HOME", "/Applications/DevEco-Studio.app/Contents"))
    hdc = deveco / "sdk/default/openharmony/toolchains/hdc"
    if not hdc.is_file():
        raise RuntimeError(f"missing hdc: {hdc}")
    return hdc


def list_targets(hdc: Path) -> list[str]:
    result = subprocess.run(
        [str(hdc), "list", "targets"], check=True, text=True, capture_output=True
    )
    return [line.strip() for line in result.stdout.replace("\r", "").splitlines() if line.strip()]


def select_target(hdc: Path, requested: str) -> str:
    targets = list_targets(hdc)
    if requested not in ("", "auto"):
        if requested not in targets:
            raise RuntimeError(f"device is not connected: {requested}")
        return requested
    if len(targets) != 1:
        raise RuntimeError(f"expected one connected device, found {len(targets)}; pass --device")
    return targets[0]


def build_recv_command(hdc: Path, device: str, output: Path) -> list[str]:
    return [str(hdc), "-t", device, "file", "recv", "-b", BUNDLE, REMOTE_ROOT, str(output)]


def _walk_json(value: object, path: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_KEYS:
                raise RuntimeError(f"diagnostic package contains forbidden field: {path}{key}")
            _walk_json(child, f"{path}{key}.")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_json(child, f"{path}{index}.")


def validate_run(run_dir: Path) -> dict[str, object]:
    manifest_path = run_dir / "manifest.json"
    summary_path = run_dir / "summary.json"
    events_path = run_dir / "events.ndjson"
    callbacks_path = run_dir / "callbacks.ndjson"
    for path in (manifest_path, summary_path, events_path, callbacks_path):
        if not path.is_file():
            raise RuntimeError(f"{run_dir.name}: missing {path.name}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 1 or manifest.get("runId") != run_dir.name:
        raise RuntimeError(f"{run_dir.name}: invalid manifest identity")
    if summary.get("runId") != run_dir.name:
        raise RuntimeError(f"{run_dir.name}: summary identity mismatch")
    _walk_json(manifest)
    _walk_json(summary)
    for ndjson_path in (events_path, callbacks_path):
        for line_number, line in enumerate(ndjson_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                _walk_json(json.loads(line))
            except json.JSONDecodeError as error:
                raise RuntimeError(f"{ndjson_path.name}:{line_number}: invalid JSON: {error}") from error
    for metadata_path in run_dir.glob("sessions/*/sdk-input.json"):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        _walk_json(metadata)
        wav_path = metadata_path.with_name("sdk-input.wav")
        if not wav_path.is_file() or wav_path.read_bytes()[:4] != b"RIFF":
            raise RuntimeError(f"{wav_path}: missing or invalid WAV")
        expected_size = int(metadata.get("bytes", -1)) + 44
        if wav_path.stat().st_size != expected_size:
            raise RuntimeError(f"{wav_path}: WAV byte count does not match metadata")
    return {"manifest": manifest, "summary": summary}


def redact_hilog(text: str, device: str) -> str:
    redacted = text.replace(device, "<DEVICE>")
    redacted = re.sub(
        r"-----BEGIN [^-]+-----.*?-----END [^-]+-----",
        "<REDACTED-PRIVATE-MATERIAL>",
        redacted,
        flags=re.DOTALL,
    )
    redacted = re.sub(r"/data/(?:storage|app|service)/\S+", "<APP_PATH>", redacted)
    redacted = re.sub(
        r"(?i)(license(?:Text)?|voiceprintIds?|hotwords?|deviceSerial)\s*[=:]\s*[^|,\s]+",
        lambda match: f"{match.group(1)}=<REDACTED>",
        redacted,
    )
    return redacted


def collect_hilog(hdc: Path, device: str) -> str:
    result = subprocess.run(
        [str(hdc), "-t", device, "hilog", "-d"], text=True, capture_output=True
    )
    return redact_hilog(result.stdout + result.stderr, device)


def discover_runs(pull_root: Path) -> list[Path]:
    return sorted(
        {path.parent for path in pull_root.rglob("manifest.json")},
        key=lambda path: path.name,
        reverse=True,
    )


def write_zip(source_root: Path, output: Path) -> None:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source_root.parent))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="auto", help="HDC target or 'auto'")
    parser.add_argument("--last", type=int, default=1, help="number of newest runs to include")
    parser.add_argument("--note", default="", help="short reproduction note")
    parser.add_argument("--output-root", type=Path, default=Path.cwd())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.last < 1:
        raise RuntimeError("--last must be >= 1")
    hdc = locate_hdc()
    device = select_target(hdc, args.device)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_root = args.output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    output_zip = output_root / f"asr-diagnostics-{stamp}.zip"
    with tempfile.TemporaryDirectory(prefix="amphion-asr-diagnostics-") as directory:
        temp = Path(directory)
        pulled = temp / "pulled"
        pulled.mkdir()
        result = subprocess.run(build_recv_command(hdc, device, pulled), text=True, capture_output=True)
        command_output = result.stdout + result.stderr
        if result.returncode != 0 or "[Fail]" in command_output:
            raise RuntimeError(f"failed to pull diagnostics: {command_output.strip()}")
        runs = discover_runs(pulled)
        if not runs:
            raise RuntimeError("no exported diagnostics found; call SpeechRecognizeSdk.exportDiagnostics first")
        package_root = temp / f"asr-diagnostics-{stamp}"
        package_root.mkdir()
        copied: list[str] = []
        for run in runs[: args.last]:
            validate_run(run)
            shutil.copytree(run, package_root / run.name)
            copied.append(run.name)
        (package_root / "hilog.txt").write_text(collect_hilog(hdc, device), encoding="utf-8")
        (package_root / "note.txt").write_text(args.note.strip() + "\n", encoding="utf-8")
        collection = {
            "schemaVersion": 1,
            "bundle": BUNDLE,
            "runIds": copied,
            "runCount": len(copied),
            "device": "<REDACTED>",
            "collectedAt": datetime.now().astimezone().isoformat(),
        }
        (package_root / "collection.json").write_text(
            json.dumps(collection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        write_zip(package_root, output_zip)
    digest = hashlib.sha256(output_zip.read_bytes()).hexdigest()
    checksum = output_zip.with_suffix(output_zip.suffix + ".sha256")
    checksum.write_text(f"{digest}  {output_zip.name}\n", encoding="utf-8")
    print(f"[OK] diagnostics: {output_zip}")
    print(f"[OK] checksum: {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
