"""Redact and copy text artifacts for persisted release-gate evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Mapping


ARCHIVE_FILES = (
    "report.json",
    "result.txt",
    "memory.csv",
    "hilog.txt",
    "inventory.json",
    "payload/corpus.json",
    "payload/manifest.txt",
)
SAFE_HILOG_MARKERS = (
    "ASR_STRESS|",
    "AmphionRuntime",
    "AmphionMetrics",
    "libsherpa",
    "sherpa_onnx",
)
LOCAL_PATH = re.compile(r"/(?:Users|home)/[^\s\"'<>|]+")
MAC_TEMP_PATH = re.compile(r"/(?:private/)?var/folders/[^\s\"'<>|]+")
RESULT_HEX = re.compile(r"(?i)(resultHex(?:\s*[=:]\s*|\"\s*:\s*\"))[0-9a-f]+")
HOSTNAME_ATTRIBUTE = re.compile(r'(?i)(hostname\s*=\s*")[^"]*(")')
FORBIDDEN_ARCHIVE_TEXT = (
    ("local home path", LOCAL_PATH),
    ("macOS temporary path", MAC_TEMP_PATH),
    ("network client identifier", re.compile(r"(?i)\bclient\s*id\b|\bclientID\b")),
    ("access token identifier", re.compile(r"(?i)access\s+token(?:ID)?")),
    ("IPv4 address", re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])")),
    (
        "UUID",
        re.compile(
            r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
        ),
    ),
    (
        "unredacted recognition text",
        re.compile(r"(?i)resultHex(?:\s*[=:]\s*|\"\s*:\s*\")[0-9a-f]+"),
    ),
    ("unredacted hostname", re.compile(r'(?i)hostname\s*=\s*"(?!redacted")')),
)


class ArchiveFailure(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def device_alias(serial: str) -> str:
    return "device-" + hashlib.sha256(serial.encode("utf-8")).hexdigest()[:12]


def redact_text(text: str, replacements: Mapping[str, str]) -> str:
    for source, replacement in sorted(replacements.items(), key=lambda item: -len(item[0])):
        if source:
            text = text.replace(source, replacement)
    text = LOCAL_PATH.sub("<LOCAL_PATH>", text)
    text = MAC_TEMP_PATH.sub("<LOCAL_TEMP>", text)
    text = RESULT_HEX.sub(r"\1<redacted>", text)
    return HOSTNAME_ATTRIBUTE.sub(r"\1redacted\2", text)


def redact_json(value: Any, replacements: Mapping[str, str]) -> Any:
    if isinstance(value, dict):
        return {
            key: "<redacted>" if key.lower() == "resulthex" else redact_json(item, replacements)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_json(item, replacements) for item in value]
    if isinstance(value, str):
        return redact_text(value, replacements)
    return value


def sanitize_artifact(relative: str, text: str, replacements: Mapping[str, str]) -> str:
    if relative.endswith(".json"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise ArchiveFailure(f"invalid JSON artifact {relative}: {error}") from error
        return json.dumps(
            redact_json(payload, replacements),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
    redacted = redact_text(text, replacements)
    if relative == "hilog.txt":
        redacted = "\n".join(
            line
            for line in redacted.splitlines()
            if any(marker in line for marker in SAFE_HILOG_MARKERS)
        )
        if redacted:
            redacted += "\n"
    return redacted


def scan_archive_text(root: Path, forbidden_values: Iterable[str]) -> None:
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        text = path.read_text(encoding="utf-8")
        for value in forbidden_values:
            if value and value in text:
                raise ArchiveFailure(f"sensitive source value remains in {path.relative_to(root)}")
        for label, pattern in FORBIDDEN_ARCHIVE_TEXT:
            if pattern.search(text):
                raise ArchiveFailure(f"{label} remains in {path.relative_to(root)}")


def copy_redacted_artifacts(
    source: Path,
    destination: Path,
    replacements: Mapping[str, str],
    *,
    require_complete: bool,
) -> List[Dict[str, object]]:
    manifest: List[Dict[str, object]] = []
    for relative in ARCHIVE_FILES:
        source_file = source / relative
        if not source_file.is_file():
            continue
        destination_file = destination / relative
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = source_file.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise ArchiveFailure(f"archive input is not UTF-8 text: {source_file}") from error
        destination_file.write_text(
            sanitize_artifact(relative, text, replacements), encoding="utf-8"
        )
        manifest.append(
            {
                "path": relative,
                "sha256": sha256_file(destination_file),
                "size_bytes": destination_file.stat().st_size,
            }
        )
    if require_complete:
        missing = [relative for relative in ARCHIVE_FILES if not (source / relative).is_file()]
        if missing:
            raise ArchiveFailure(
                f"canonical run is missing required artifact {missing[0]}: {source}"
            )
    if not manifest:
        raise ArchiveFailure(f"run has no archivable artifacts: {source}")
    return manifest
