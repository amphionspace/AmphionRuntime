#!/usr/bin/env python3
"""Track ASR SDK deliveries and render commit-backed release notes."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional


SCHEMA_VERSION = 2
PLATFORMS = {"android": "Android", "harmony": "HarmonyOS"}
COMMON_SOURCE_PREFIXES = (
    "asr/common/",
    "shared/",
    "third_party/patches/sherpa-amphion/",
    "tools/delivery/",
)
PLATFORM_SOURCE_PREFIXES = {
    "android": (
        "asr/android/",
        "asr/tools/delivery/",
        "asr/tools/04_build_android_so.sh",
        "asr/tools/05_package_aar_libs.sh",
        "asr/tools/08_pack_sdk_assets.sh",
        "asr/tools/requirements-android-ort.txt",
        "asr/tools/license/issue_android_asr_eval.sh",
        "asr/tools/verify_packed_model_assets.py",
        "asr/tools/tests/test_verify_packed_model_assets.py",
    ),
    "harmony": (
        "asr/harmony/",
        "delivery/harmony-dingqiao/",
        "asr/tools/demo-model/",
        "asr/tools/04_build_harmony_so.sh",
        "asr/tools/05_package_har_libs.sh",
        "asr/tools/08_pack_harmony_assets.sh",
        "asr/tools/build_harmony_asset_manifest.py",
        "asr/tools/convert_harmony_ort.py",
        "asr/tools/requirements-harmony-ort.txt",
        "asr/tools/sync_harmony_police_assets.py",
        "asr/tools/test_harmony_police_parity.py",
        "asr/tools/tests/test_build_harmony_asset_manifest.py",
        "asr/tools/tests/test_convert_harmony_ort.py",
        "asr/tools/tests/test_harmony_",
        "asr/tools/license/issue_harmony_asr_eval.sh",
    ),
}
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PLATFORM_SCOPE = re.compile(r"^[a-z0-9-]+(?:!)?\((android|harmony)\)(?:!)?:")
REQUIRED_ENTRY_FIELDS = {
    "platform",
    "version",
    "source_commit",
    "delivered_at",
    "artifact",
    "artifact_sha256",
    "artifact_size_bytes",
    "provenance_sha256",
}


class ReleaseTrackerError(RuntimeError):
    pass


def _run_git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or error.stdout.strip()
        raise ReleaseTrackerError(f"git {' '.join(args)} failed: {detail}") from error
    return result.stdout.strip()


def resolve_commit(repo: Path, commit: str) -> str:
    resolved = _run_git(repo, "rev-parse", f"{commit}^{{commit}}")
    if not FULL_COMMIT.fullmatch(resolved):
        raise ReleaseTrackerError(f"invalid resolved commit: {resolved}")
    return resolved


def load_history(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseTrackerError(f"cannot read release history {path}: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ReleaseTrackerError(f"release history schema_version must be {SCHEMA_VERSION}")
    deliveries = payload.get("deliveries")
    if not isinstance(deliveries, list):
        raise ReleaseTrackerError("release history deliveries must be a list")
    seen = set()
    for index, entry in enumerate(deliveries):
        if not isinstance(entry, dict) or set(entry) != REQUIRED_ENTRY_FIELDS:
            raise ReleaseTrackerError(f"delivery #{index + 1} has invalid fields")
        platform = entry["platform"]
        version = entry["version"]
        key = (platform, version)
        if platform not in PLATFORMS:
            raise ReleaseTrackerError(f"delivery #{index + 1} has invalid platform {platform!r}")
        if not isinstance(version, str) or not SEMVER.fullmatch(version):
            raise ReleaseTrackerError(f"delivery #{index + 1} has invalid version {version!r}")
        if key in seen:
            raise ReleaseTrackerError(f"{platform} {version} is already recorded")
        seen.add(key)
        if not isinstance(entry["source_commit"], str) or not FULL_COMMIT.fullmatch(
            entry["source_commit"]
        ):
            raise ReleaseTrackerError(f"delivery #{index + 1} has invalid source_commit")
        if not isinstance(entry["delivered_at"], str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}", entry["delivered_at"]
        ):
            raise ReleaseTrackerError(f"delivery #{index + 1} has invalid delivered_at")
        if not isinstance(entry["artifact"], str) or not entry["artifact"]:
            raise ReleaseTrackerError(f"delivery #{index + 1} has invalid artifact")
        if Path(entry["artifact"]).name != entry["artifact"] or not entry["artifact"].endswith(
            ".zip"
        ):
            raise ReleaseTrackerError(f"delivery #{index + 1} artifact must be a ZIP basename")
        if not isinstance(entry["artifact_sha256"], str) or not SHA256.fullmatch(
            entry["artifact_sha256"]
        ):
            raise ReleaseTrackerError(f"delivery #{index + 1} has invalid artifact_sha256")
        if not isinstance(entry["artifact_size_bytes"], int) or entry[
            "artifact_size_bytes"
        ] <= 0:
            raise ReleaseTrackerError(f"delivery #{index + 1} has invalid artifact_size_bytes")
        if not isinstance(entry["provenance_sha256"], str) or not SHA256.fullmatch(
            entry["provenance_sha256"]
        ):
            raise ReleaseTrackerError(f"delivery #{index + 1} has invalid provenance_sha256")
    return payload


def _previous_delivery(history: Dict[str, Any], platform: str) -> Optional[Dict[str, str]]:
    matches = [entry for entry in history["deliveries"] if entry["platform"] == platform]
    return matches[-1] if matches else None


def _changed_paths(repo: Path, commit: str) -> List[str]:
    return _run_git(
        repo, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", commit
    ).splitlines()


def _commit_affects_platform(
    repo: Path, commit: str, subject: str, history_path: Path, platform: str
) -> bool:
    scoped_platform = PLATFORM_SCOPE.match(subject)
    if scoped_platform is not None and scoped_platform.group(1) != platform:
        return False
    try:
        relative_history = history_path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        relative_history = ""
    changed = _changed_paths(repo, commit)
    if not changed or (relative_history and set(changed) == {relative_history}):
        return False
    prefixes = COMMON_SOURCE_PREFIXES + PLATFORM_SOURCE_PREFIXES[platform]
    return any(path.startswith(prefixes) for path in changed)


def render_changelog(
    *,
    repo: Path,
    history_path: Path,
    platform: str,
    version: str,
    source_commit: str,
) -> str:
    if platform not in PLATFORMS:
        raise ReleaseTrackerError(f"unsupported platform: {platform}")
    if not SEMVER.fullmatch(version):
        raise ReleaseTrackerError(f"version must be SemVer MAJOR.MINOR.PATCH: {version}")
    history = load_history(history_path)
    if any(
        entry["platform"] == platform and entry["version"] == version
        for entry in history["deliveries"]
    ):
        raise ReleaseTrackerError(f"{platform} {version} is already recorded")
    current = resolve_commit(repo, source_commit)
    previous = _previous_delivery(history, platform)

    lines = [
        "# ASR SDK 更新日志",
        "",
        f"## {PLATFORMS[platform]} ASR SDK {version}",
        "",
        f"- 构建 commit：`{current}`",
    ]
    if previous is None:
        lines.extend(["- 上一交付：无", "", "### Commit 变更", ""])
        commit_range = current
    else:
        previous_commit = resolve_commit(repo, previous["source_commit"])
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", previous_commit, current], cwd=repo
        )
        if ancestor.returncode != 0:
            raise ReleaseTrackerError(
                f"previous delivery commit {previous_commit} is not an ancestor of {current}"
            )
        lines.extend(
            [
                f"- 上一交付：{previous['version']} (`{previous_commit}`)",
                "",
                "### Commit 变更",
                "",
            ]
        )
        commit_range = f"{previous_commit}..{current}"

    raw_log = _run_git(repo, "log", "--reverse", "--format=%H%x1f%s", commit_range)
    changes: List[str] = []
    for row in raw_log.splitlines():
        if not row:
            continue
        commit, subject = row.split("\x1f", 1)
        if not _commit_affects_platform(repo, commit, subject, history_path, platform):
            continue
        changes.append(f"- `{commit[:12]}` {subject}")
    lines.extend(changes or ["- 本次交付没有新的源码 commit。"])
    return "\n".join(lines) + "\n"


def _read_provenance(payload_bytes: bytes, name: str) -> Dict[str, str]:
    if name.lower().endswith(".json"):
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
            return {
                "version": payload["delivery_version"],
                "commit": payload["source"]["commit"],
            }
        except (UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
            raise ReleaseTrackerError(f"invalid Harmony provenance in {name}: {error}") from error
    try:
        fields = {}
        for line in payload_bytes.decode("utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                fields[key] = value
        return {"version": fields["delivery_version"], "commit": fields["git_commit_full"]}
    except (UnicodeError, KeyError) as error:
        raise ReleaseTrackerError(f"invalid Android provenance in {name}: {error}") from error


def _read_artifact_provenance(artifact_path: Path, platform: str) -> tuple[Dict[str, str], bytes]:
    if not artifact_path.is_file() or artifact_path.suffix.lower() != ".zip":
        raise ReleaseTrackerError("artifact must be an existing final ZIP")
    suffix = "VERSION.txt" if platform == "android" else "docs/BUILD_PROVENANCE.json"
    try:
        with zipfile.ZipFile(artifact_path) as archive:
            bad = archive.testzip()
            if bad is not None:
                raise ReleaseTrackerError(f"artifact ZIP CRC failed: {bad}")
            matches = [name for name in archive.namelist() if name.endswith(f"/{suffix}")]
            if len(matches) != 1:
                raise ReleaseTrackerError(
                    f"artifact must contain exactly one {suffix}, found {len(matches)}"
                )
            name = matches[0]
            payload = archive.read(name)
    except (OSError, zipfile.BadZipFile) as error:
        raise ReleaseTrackerError(f"cannot read artifact ZIP {artifact_path}: {error}") from error
    return _read_provenance(payload, name), payload


def _history_lock_path(history_path: Path) -> Path:
    identity = hashlib.sha256(str(history_path.resolve()).encode("utf-8")).hexdigest()
    return Path(tempfile.gettempdir()) / f"amphion-asr-release-history-{identity}.lock"


def record_delivery(
    *,
    repo: Path,
    history_path: Path,
    platform: str,
    version: str,
    source_commit: str,
    delivered_at: str,
    artifact_path: Path,
) -> Dict[str, str]:
    if platform not in PLATFORMS:
        raise ReleaseTrackerError(f"unsupported platform: {platform}")
    if not SEMVER.fullmatch(version):
        raise ReleaseTrackerError(f"version must be SemVer MAJOR.MINOR.PATCH: {version}")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", delivered_at):
        raise ReleaseTrackerError(f"delivered_at must be YYYY-MM-DD: {delivered_at}")
    resolved = resolve_commit(repo, source_commit)
    artifact_path = artifact_path.resolve()
    provenance, provenance_payload = _read_artifact_provenance(artifact_path, platform)
    if provenance["version"] != version:
        raise ReleaseTrackerError(
            f"provenance version {provenance['version']} does not match {version}"
        )
    provenance_commit = resolve_commit(repo, provenance["commit"])
    if provenance_commit != resolved:
        raise ReleaseTrackerError(
            f"provenance commit {provenance_commit} does not match {resolved}"
        )
    artifact = artifact_path.name
    artifact_digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    provenance_digest = hashlib.sha256(provenance_payload).hexdigest()
    entry = {
        "platform": platform,
        "version": version,
        "source_commit": resolved,
        "delivered_at": delivered_at,
        "artifact": artifact,
        "artifact_sha256": artifact_digest,
        "artifact_size_bytes": artifact_path.stat().st_size,
        "provenance_sha256": provenance_digest,
    }
    history_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _history_lock_path(history_path)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        history = load_history(history_path)
        if any(
            delivery["platform"] == platform and delivery["version"] == version
            for delivery in history["deliveries"]
        ):
            raise ReleaseTrackerError(f"{platform} {version} is already recorded")
        history["deliveries"].append(entry)
        temporary_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=history_path.parent,
                prefix=f".{history_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(history, temporary, ensure_ascii=False, indent=2)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, history_path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
    return entry


def _default_repo() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=_default_repo())
    parser.add_argument("--history", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    changelog = subparsers.add_parser("changelog")
    changelog.add_argument("--platform", choices=sorted(PLATFORMS), required=True)
    changelog.add_argument("--version", required=True)
    changelog.add_argument("--source-commit", default="HEAD")
    changelog.add_argument("--output", type=Path, required=True)

    record = subparsers.add_parser("record")
    record.add_argument("--platform", choices=sorted(PLATFORMS), required=True)
    record.add_argument("--version", required=True)
    record.add_argument("--source-commit", default="HEAD")
    record.add_argument("--delivered-at", required=True)
    record.add_argument("--artifact", type=Path, required=True)

    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    history_path = (args.history or repo / "delivery/asr-sdk-release-history.json").resolve()
    try:
        if args.command == "changelog":
            output = args.output.resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                render_changelog(
                    repo=repo,
                    history_path=history_path,
                    platform=args.platform,
                    version=args.version,
                    source_commit=args.source_commit,
                ),
                encoding="utf-8",
            )
            print(f"[OK] wrote release changelog: {output}")
        else:
            entry = record_delivery(
                repo=repo,
                history_path=history_path,
                platform=args.platform,
                version=args.version,
                source_commit=args.source_commit,
                delivered_at=args.delivered_at,
                artifact_path=args.artifact,
            )
            print(
                f"[OK] recorded {entry['platform']} {entry['version']} "
                f"at {entry['source_commit']}"
            )
    except ReleaseTrackerError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
