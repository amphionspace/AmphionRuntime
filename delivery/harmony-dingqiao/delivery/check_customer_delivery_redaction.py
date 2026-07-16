#!/usr/bin/env python3
"""Reject customer documents that contain common local or test-only identifiers."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import tarfile
from typing import Iterable


TEXT_SUFFIXES = {"", ".json", ".md", ".txt"}
ARCHIVE_TEXT_SUFFIXES = TEXT_SUFFIXES | {
    ".csv", ".ets", ".json5", ".ts", ".tsv", ".xml", ".yaml", ".yml"
}
REDACTED_VALUES = {"REDACTED", "已脱敏"}
SENSITIVE_JSON_KEYS = {
    "deviceid",
    "deviceidentifier",
    "devicemodel",
    "licenseid",
    "odid",
    "serial",
    "serialnumber",
    "sn",
    "sourceidentifiers",
}

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "local user home path",
        re.compile(r"(?:/Users/[^\s`'\"]+|/home/[^\s`'\"]+|[A-Za-z]:\\Users\\[^\s`'\"]+)"),
    ),
    ("macOS temporary path", re.compile(r"/var/folders/[^\s`'\"]+")),
    ("private configuration path", re.compile(r"(?:^|[\s`'\"])(?:\.secure|private)/", re.MULTILINE)),
    (
        "internal stress run identifier",
        re.compile(r"\b20\d{6}-\d{6}-[a-z0-9-]+-[0-9a-f]{8}\b"),
    ),
    (
        "literal device identifier",
        re.compile(
            r"\b(?:device(?:_identifier|Id)|serial(?:Number)?|SN|ODID)\s*[:=]\s*"
            r"[\"']?(?!REDACTED\b|已脱敏\b)(?=[A-Za-z0-9_-]{8,}\b)"
            r"(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{8,}",
            re.IGNORECASE,
        ),
    ),
    (
        "probable device serial",
        re.compile(
            r"\b(?=[A-Z0-9]{12,20}\b)(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*\d)"
            r"[A-Z0-9]{12,20}\b"
        ),
    ),
    (
        "hardware product code",
        re.compile(r"\b[A-Z]{3}-(?=[A-Z0-9]{4,}\b)(?=[A-Z0-9]*\d)[A-Z0-9]{4,}\b"),
    ),
    ("test-only license identifier", re.compile(r"\bLOCAL-[A-Z0-9_-]{4,}\b")),
    ("private key material", re.compile(r"-----BEGIN (?:EC |RSA )?PRIVATE KEY-----")),
)


def iter_text_files(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and (child.suffix in TEXT_SUFFIXES or child.name == "NOTICE"):
                    yield child
        elif path.is_file():
            yield path


def _json_violations(value: object, location: str = "$") -> list[str]:
    violations: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}"
            normalized_key = re.sub(r"[^a-z0-9]", "", key.lower())
            redacted = isinstance(child, str) and child in REDACTED_VALUES
            if normalized_key in SENSITIVE_JSON_KEYS and not redacted:
                violations.append(f"unredacted sensitive JSON value at {child_location}")
            violations.extend(_json_violations(child, child_location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            violations.extend(_json_violations(child, f"{location}[{index}]"))
    return violations


def find_text_violations(text: str, suffix: str) -> list[str]:
    violations: list[str] = []
    for label, pattern in PATTERNS:
        match = pattern.search(text)
        if match:
            line = text.count("\n", 0, match.start()) + 1
            violations.append(f"{label} at line {line}")
    if suffix == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            violations.append(f"invalid JSON: {error}")
        else:
            violations.extend(_json_violations(payload))
    return violations


def find_violations(path: Path) -> list[str]:
    return find_text_violations(path.read_text(encoding="utf-8"), path.suffix)


def find_archive_violations(path: Path) -> list[str]:
    violations: list[str] = []
    try:
        archive = tarfile.open(path, "r:gz")
    except (OSError, tarfile.TarError) as error:
        return [f"invalid HAR archive: {error}"]
    with archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            member_path = Path(member.name)
            if member_path.suffix not in ARCHIVE_TEXT_SUFFIXES and member_path.name not in {
                "LICENSE", "NOTICE"
            }:
                continue
            stream = archive.extractfile(member)
            if stream is None:
                continue
            try:
                text = stream.read().decode("utf-8")
            except UnicodeDecodeError:
                continue
            for violation in find_text_violations(text, member_path.suffix):
                violations.append(f"{member.name}: {violation}")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    archives = [path for path in args.paths if path.is_file() and path.suffix == ".har"]
    files = list(iter_text_files(path for path in args.paths if path not in archives))
    if not files and not archives:
        parser.error("no customer text files found")

    failed = False
    for path in files:
        for violation in find_violations(path):
            failed = True
            print(f"[ERROR] {path}: {violation}")
    for path in archives:
        for violation in find_archive_violations(path):
            failed = True
            print(f"[ERROR] {path}!/{violation}")
    if failed:
        return 1

    print(
        f"[OK] customer delivery redaction check passed: "
        f"{len(files)} files, {len(archives)} HAR archives"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
