#!/usr/bin/env python3
"""Reject unredacted device evidence and raw system logs tracked by Git."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Iterable


EVIDENCE_PREFIXES = (
    "asr/android/reports/",
    "delivery/harmony-dingqiao/evidence/",
)
TEXT_SUFFIXES = {".csv", ".json", ".jsonl", ".md", ".tsv", ".txt", ".xml"}
RAW_SYSTEM_LOG_NAMES = re.compile(r"^(?:logcat\.txt|tombstone[^/]*\.txt)$", re.IGNORECASE)
LOCAL_HOME = re.compile(r"(?:/Users/|/home/)[^\s`'\"<>|]+")
PRIVATE_KEY = re.compile(r"-----BEGIN (?:EC |RSA )?PRIVATE KEY-----")
RESULT_HEX = re.compile(r"(?i)resultHex(?:\s*[=:]\s*|\"\s*:\s*\")[0-9a-f]+")
LITERAL_DEVICE = re.compile(
    r"(?i)\b(?:device(?:Id|_id)?|serial(?:Number)?|SN|ODID)\s*[=:]\s*"
    r"[\"']?(?!device-[0-9a-f]{12}\b|REDACTED\b|<redacted>\b|已脱敏\b)"
    r"(?=[A-Za-z0-9_-]{8,}\b)(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{8,}"
)
SENSITIVE_JSON_KEYS = {"device", "deviceid", "odid", "serial", "serialnumber", "sn"}
SAFE_IDENTIFIER = re.compile(r"^(?:device-[0-9a-f]{12}|REDACTED|<redacted>|已脱敏)$")


def tracked_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=repo_root, check=True, capture_output=True
    )
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def _json_identifier_violations(value: object, location: str = "$") -> list[str]:
    violations: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}"
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if normalized in SENSITIVE_JSON_KEYS and isinstance(child, str):
                if "*" not in child and not SAFE_IDENTIFIER.fullmatch(child):
                    violations.append(f"unredacted device identifier at {child_location}")
            violations.extend(_json_identifier_violations(child, child_location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            violations.extend(_json_identifier_violations(child, f"{location}[{index}]"))
    return violations


def find_violations(repo_root: Path, paths: Iterable[str]) -> list[str]:
    violations: list[str] = []
    for relative in sorted(paths):
        if not relative.startswith(EVIDENCE_PREFIXES):
            continue
        path = PurePosixPath(relative)
        if RAW_SYSTEM_LOG_NAMES.fullmatch(path.name):
            violations.append(f"raw system log must not be tracked: {relative}")
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        source = repo_root / relative
        try:
            text = source.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            violations.append(f"cannot inspect evidence {relative}: {error}")
            continue
        for label, pattern in (
            ("local home path", LOCAL_HOME),
            ("private key material", PRIVATE_KEY),
            ("unredacted recognition text", RESULT_HEX),
            ("literal device identifier", LITERAL_DEVICE),
        ):
            if pattern.search(text):
                violations.append(f"{label} in tracked evidence: {relative}")
        if path.suffix.lower() == ".json":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as error:
                violations.append(f"invalid evidence JSON {relative}: {error}")
            else:
                for violation in _json_identifier_violations(payload):
                    violations.append(f"{violation}: {relative}")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    violations = find_violations(repo_root, tracked_files(repo_root))
    if violations:
        for violation in violations:
            print(f"ERROR: {violation}")
        return 1
    print("repository observability evidence: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
