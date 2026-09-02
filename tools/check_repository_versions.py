#!/usr/bin/env python3
"""Keep the root README version table aligned with platform build metadata."""

from __future__ import annotations

import argparse
import re
from collections.abc import Mapping
from pathlib import Path


VERSION_SOURCES = {
    "ASR Android": (
        "asr/android/gradle.properties",
        r"(?m)^AMPHION_RUNTIME_VERSION=(\S+)$",
    ),
    "ASR HarmonyOS": (
        "asr/harmony/sdk/oh-package.json5",
        r'"version"\s*:\s*"([^"]+)"',
    ),
    "ASR iOS 预览版": (
        "asr/ios/AmphionRuntime.podspec",
        r"s\.version\s*=\s*'([^']+)'",
    ),
    "TTS Android": (
        "tts/android/build.gradle.kts",
        r'(?m)^val sdkVersion = "([^"]+)"$',
    ),
    "TTS HarmonyOS": (
        "tts/harmony/sdk/oh-package.json5",
        r'"version"\s*:\s*"([^"]+)"',
    ),
}
MIRRORED_VERSION_SOURCES = {
    "ASR iOS 预览版": (
        "asr/ios/Sources/AmphionRuntime/AsrSdk.swift",
        r'public let version: String = "([^"]+)"',
    ),
}


def read_versions(repo_root: Path) -> dict[str, str]:
    versions: dict[str, str] = {}
    for component, (relative_path, pattern) in VERSION_SOURCES.items():
        path = repo_root / relative_path
        match = re.search(pattern, path.read_text(encoding="utf-8"))
        if match is None:
            raise ValueError(f"cannot read {component} version from {relative_path}")
        versions[component] = match.group(1)
    return versions


def find_source_violations(repo_root: Path, versions: Mapping[str, str]) -> list[str]:
    violations: list[str] = []
    for component, (relative_path, pattern) in MIRRORED_VERSION_SOURCES.items():
        match = re.search(pattern, (repo_root / relative_path).read_text(encoding="utf-8"))
        actual = match.group(1) if match else "unreadable"
        expected = versions[component]
        if actual != expected:
            violations.append(
                f"mirrored version is stale: {relative_path} expected={expected} actual={actual}"
            )
    return violations


def find_readme_violations(readme: str, versions: Mapping[str, str]) -> list[str]:
    violations: list[str] = []
    for component, version in versions.items():
        expected = f"| {component} | `{version}` |"
        if expected not in readme:
            violations.append(
                f"README version table is stale: expected {component}={version}"
            )
    if "整库版本号统一" in readme:
        violations.append("README must not claim a single repository-wide SDK version")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    try:
        versions = read_versions(repo_root)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}")
        return 1
    violations = find_source_violations(repo_root, versions)
    violations.extend(find_readme_violations(
        (repo_root / "README.md").read_text(encoding="utf-8"),
        versions,
    ))
    if violations:
        for violation in violations:
            print(f"ERROR: {violation}")
        return 1
    print("repository versions: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
