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


BUNDLE = "com.amphion.asr.harmony.debug"
REMOTE_ROOT_TEMPLATE = "/data/storage/el2/base/haps/{module}/files/asr-diagnostics"
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


def discover_module(hdc: Path, device: str, bundle: str) -> str:
    result = subprocess.run(
        [str(hdc), "-t", device, "shell", "bm", "dump", "-n", bundle],
        check=True,
        text=True,
        capture_output=True,
    )
    names = re.findall(r'"moduleName"\s*:\s*"([^"\\]+)"', result.stdout)
    names = list(dict.fromkeys(name for name in names if name))
    if not names:
        raise RuntimeError(f"cannot discover HAP module for bundle: {bundle}")
    if len(names) > 1:
        raise RuntimeError(
            f"bundle has multiple HAP modules ({', '.join(names)}); pass --module"
        )
    return names[0]


def build_recv_command(
    hdc: Path, device: str, output: Path, bundle: str, module: str
) -> list[str]:
    remote_root = REMOTE_ROOT_TEMPLATE.format(module=module)
    return [str(hdc), "-t", device, "file", "recv", "-b", bundle, remote_root, str(output)]


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
    schema = manifest.get("schemaVersion")
    if schema not in (1, 2) or manifest.get("runId") != run_dir.name:
        raise RuntimeError(f"{run_dir.name}: invalid manifest identity")
    if summary.get("runId") != run_dir.name:
        raise RuntimeError(f"{run_dir.name}: summary identity mismatch")
    _walk_json(manifest)
    _walk_json(summary)
    if schema == 2:
        required = (
            "build-identity.json",
            "model-manifest.json",
            "effective-config.json",
            "resource-samples.csv",
            "native-state.json",
        )
        for name in required:
            if not (run_dir / name).is_file():
                raise RuntimeError(f"{run_dir.name}: missing {name}")
        for name in required:
            path = run_dir / name
            if path.suffix == ".json":
                _walk_json(json.loads(path.read_text(encoding="utf-8")))
        resource_header = (run_dir / "resource-samples.csv").read_text(
            encoding="utf-8"
        ).splitlines()[0]
        if not resource_header.startswith("wallTimeMs,rssKb,"):
            raise RuntimeError(f"{run_dir.name}: invalid resource-samples.csv")
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
    if schema == 2:
        for timeline in run_dir.glob("sessions/*/timeline.json"):
            result_path = timeline.with_name("result.json")
            if not result_path.is_file():
                raise RuntimeError(f"{result_path}: missing session result")
            _walk_json(json.loads(result_path.read_text(encoding="utf-8")))
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


def filter_hilog_for_bundle(text: str, bundle: str) -> str:
    lines = text.splitlines()
    owner = re.compile(
        rf"^(?:\S+\s+){{2}}(\d+)\s+\d+\s+\S+\s+\S+/{re.escape(bundle)}/"
    )
    pids = {match.group(1) for line in lines if (match := owner.match(line))}
    if not pids:
        return "No hilog process identity found for the requested bundle.\n"
    process_line = re.compile(r"^(?:\S+\s+){2}(\d+)\s+")
    selected = [
        line for line in lines
        if (match := process_line.match(line)) and match.group(1) in pids
    ]
    return "\n".join(selected) + ("\n" if selected else "")


def collect_hilog(hdc: Path, device: str, bundle: str) -> str:
    result = subprocess.run(
        [str(hdc), "-t", device, "shell", "hilog", "-x"],
        text=True,
        errors="replace",
        capture_output=True,
        timeout=30,
    )
    selected = filter_hilog_for_bundle(result.stdout + result.stderr, bundle)
    return redact_hilog(selected, device)


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


def retain_relevant_sessions(run_dir: Path) -> list[str]:
    """Default privacy boundary: keep abnormal sessions, or only the newest session."""
    summary_path = run_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    sessions = summary.get("sessions", [])
    selected = [
        str(session.get("sessionId", ""))
        for session in sessions
        if isinstance(session, dict) and session.get("abnormal") is True
    ]
    if not selected and sessions:
        latest = sessions[-1]
        if isinstance(latest, dict):
            selected = [str(latest.get("sessionId", ""))]
    selected = [session_id for session_id in selected if session_id]
    if not selected:
        return []
    session_root = run_dir / "sessions"
    if session_root.is_dir():
        for child in session_root.iterdir():
            if child.is_dir() and child.name not in selected:
                shutil.rmtree(child)
    for name in ("events.ndjson", "callbacks.ndjson"):
        path = run_dir / name
        retained: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("sessionId", "") in ("", *selected):
                retained.append(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
        path.write_text("\n".join(retained) + ("\n" if retained else ""), encoding="utf-8")
    kept_summaries = [
        session for session in sessions
        if isinstance(session, dict) and str(session.get("sessionId", "")) in selected
    ]
    summary["sessions"] = kept_summaries
    summary["sessionCount"] = len(kept_summaries)
    summary["privacySessionSelection"] = "abnormal-or-newest"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return selected


def encrypt_archive(archive: Path, password_file: Path) -> Path:
    password_file = password_file.expanduser().resolve()
    if not password_file.is_file() or password_file.stat().st_size == 0:
        raise RuntimeError("--encrypt-password-file must reference a non-empty file")
    encrypted = archive.with_suffix(archive.suffix + ".enc")
    subprocess.run(
        [
            "openssl", "enc", "-aes-256-cbc", "-salt", "-pbkdf2", "-iter", "200000",
            "-in", str(archive), "-out", str(encrypted), "-pass", f"file:{password_file}",
        ],
        check=True,
        capture_output=True,
    )
    archive.unlink()
    return encrypted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="auto", help="HDC target or 'auto'")
    parser.add_argument("--bundle", default=BUNDLE, help="application bundle name")
    parser.add_argument("--module", default="", help="HAP module name; auto-detected by default")
    parser.add_argument("--last", type=int, default=1, help="number of newest runs to include")
    parser.add_argument("--note", default="", help="short reproduction note")
    parser.add_argument("--output-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--include-all-sessions", action="store_true",
        help="include every session in selected runs (privacy-sensitive)",
    )
    parser.add_argument(
        "--encrypt-password-file", type=Path,
        help="optionally encrypt the ZIP with OpenSSL AES-256-CBC/PBKDF2",
    )
    parser.add_argument(
        "--build-identity", type=Path,
        help="verified delivery build-identity.json to attach to every run",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.last < 1:
        raise RuntimeError("--last must be >= 1")
    hdc = locate_hdc()
    device = select_target(hdc, args.device)
    module = args.module.strip() or discover_module(hdc, device, args.bundle)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_root = args.output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    output_zip = output_root / f"asr-diagnostics-{stamp}.zip"
    build_identity = args.build_identity
    bundled_identity = Path(__file__).resolve().with_name("build-identity.json")
    if build_identity is None and bundled_identity.is_file():
        build_identity = bundled_identity
    with tempfile.TemporaryDirectory(prefix="amphion-asr-diagnostics-") as directory:
        temp = Path(directory)
        pulled = temp / "pulled"
        pulled.mkdir()
        result = subprocess.run(
            build_recv_command(hdc, device, pulled, args.bundle, module),
            text=True,
            capture_output=True,
        )
        command_output = result.stdout + result.stderr
        if result.returncode != 0 or "[Fail]" in command_output:
            raise RuntimeError(f"failed to pull diagnostics: {command_output.strip()}")
        runs = discover_runs(pulled)
        if not runs:
            raise RuntimeError("no exported diagnostics found; call SpeechRecognizeSdk.exportDiagnostics first")
        package_root = temp / f"asr-diagnostics-{stamp}"
        package_root.mkdir()
        copied: list[str] = []
        hilog_text = collect_hilog(hdc, device, args.bundle)
        for run in runs[: args.last]:
            validate_run(run)
            destination = package_root / run.name
            shutil.copytree(run, destination)
            if not args.include_all_sessions:
                retain_relevant_sessions(destination)
            (destination / "hilog.txt").write_text(hilog_text, encoding="utf-8")
            if build_identity is not None:
                identity = build_identity.expanduser().resolve()
                json.loads(identity.read_text(encoding="utf-8"))
                shutil.copy2(identity, destination / "build-identity.json")
            copied.append(run.name)
        (package_root / "hilog.txt").write_text(
            hilog_text, encoding="utf-8"
        )
        (package_root / "note.txt").write_text(args.note.strip() + "\n", encoding="utf-8")
        collection = {
            "schemaVersion": 1,
            "bundle": args.bundle,
            "module": module,
            "runIds": copied,
            "runCount": len(copied),
            "device": "<REDACTED>",
            "collectedAt": datetime.now().astimezone().isoformat(),
        }
        (package_root / "collection.json").write_text(
            json.dumps(collection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        write_zip(package_root, output_zip)
    final_output = output_zip
    if args.encrypt_password_file is not None:
        final_output = encrypt_archive(output_zip, args.encrypt_password_file)
    digest = hashlib.sha256(final_output.read_bytes()).hexdigest()
    checksum = final_output.with_suffix(final_output.suffix + ".sha256")
    checksum.write_text(f"{digest}  {final_output.name}\n", encoding="utf-8")
    print(f"[OK] diagnostics: {final_output}")
    print(f"[OK] checksum: {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
