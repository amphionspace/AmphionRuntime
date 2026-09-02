#!/usr/bin/env python3
"""Reject tracked files that violate the repository layout contract."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath


ALLOWED_ROOT_MARKDOWN = {"AGENTS.md", "README.md"}
ALLOWED_ROOT_DIRECTORIES = {
    ".cursor",
    ".github",
    "asr",
    "ci",
    "delivery",
    "docs",
    "shared",
    "third_party",
    "tools",
    "tts",
}
REQUIRED_FILES = {
    "asr/docs/api/语音识别SDK接口-20260622.md",
    "tts/docs/api/语音合成SDK接口.md",
    "tts/docs/optimization/TN_SIZE_OPT_REPORT.md",
}
LICENSE_DELIVERY_PREFIX = "amphion-dingqiao-license-v"
SUMMARY_GLOB = "tts/android/testdata/dingqiao_batch_cases/*_summary.json"
LOCAL_HOME_PREFIXES = ("/Users/", "/home/")
LEGACY_TTS_PATHS = {
    "scripts/build_dingqiao_android_native.sh": "tts/tools/tn/",
    "scripts/build_dingqiao_harmony_tn.sh": "tts/tools/tn/",
    "scripts/build_slim_icu_data.sh": "tts/tools/tn/",
    "scripts/icu_tn_data_filter.json": "tts/tools/tn/",
    "scripts/tn_icu_slim": "tts/tools/tn/icu_slim/",
    "scripts/tn_pronunciation_fix": "tts/tools/tn/pronunciation_fix/",
    "tools/dingqiao-android": "tts/tools/android/",
    "tools/dingqiao-onnx-export": "tts/tools/onnx-export/",
}
LEGACY_ASR_PATHS = {
    "evaluation": "asr/evaluation/",
    "scripts/mac_prep": "asr/tools/mac_prep/",
}
REQUIRED_GITLINKS = {
    "third_party/sherpa-onnx": "f3b1a9da8d6e0e6cdb21387d41d25f8c8e10d3cc",
}
GENERATED_FILE_PREFIXES = {
    "tts/android/external-resources/",
    "tts/android/aarHost/src/androidTest/assets/",
    "tts/training/dingqiao_lits/lits/utils/monotonic_align/core.cpython-",
}
GENERATED_FILES = {
    "tts/android/sdk/src/androidTest/assets/"
    "pronunciation-golden-round3-results-with-pinyin-fixed-round15.jsonl",
    "tts/harmony/sdk/src/main/cpp/libs/arm64-v8a/libonnxruntime.so",
    "tts/training/dingqiao_lits/lits/utils/monotonic_align/core.c",
}
DUPLICATED_SOURCE_PREFIXES = {
    "tts/training/dingqiao_lits/vocos-24k/vocos/",
}


def tracked_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def tracked_gitlinks(repo_root: Path) -> dict[str, str]:
    result = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    gitlinks: dict[str, str] = {}
    for item in result.stdout.split(b"\0"):
        if not item:
            continue
        metadata, path = item.split(b"\t", 1)
        mode, object_id, _stage = metadata.decode("ascii").split()
        if mode == "160000":
            gitlinks[path.decode("utf-8")] = object_id
    return gitlinks


def find_path_violations(paths: Iterable[str]) -> list[str]:
    tracked = set(paths)
    violations: list[str] = []

    for item in sorted(tracked):
        parts = PurePosixPath(item).parts
        if any(part != part.rstrip() for part in parts):
            violations.append(f"tracked path has trailing whitespace: {item!r}")

        if len(parts) == 1 and item.lower().endswith((".md", ".markdown")):
            if item not in ALLOWED_ROOT_MARKDOWN:
                violations.append(f"root Markdown must belong to a module or docs/: {item}")

        if len(parts) > 1 and parts[0] not in ALLOWED_ROOT_DIRECTORIES:
            violations.append(f"tracked root directory is not module-owned: {parts[0]}")

        if parts and parts[0].startswith(LICENSE_DELIVERY_PREFIX):
            violations.append(f"license delivery directory must not be tracked at root: {parts[0]}")

        for legacy_path, module_path in LEGACY_TTS_PATHS.items():
            if item == legacy_path or item.startswith(f"{legacy_path}/"):
                violations.append(f"TTS tooling must live under {module_path}: {item}")
                break

        for legacy_path, module_path in LEGACY_ASR_PATHS.items():
            if item == legacy_path or item.startswith(f"{legacy_path}/"):
                violations.append(f"ASR tooling must live under {module_path}: {item}")
                break

        if item in GENERATED_FILES or any(
            item.startswith(prefix) for prefix in GENERATED_FILE_PREFIXES
        ):
            violations.append(f"generated copy must not be tracked: {item}")

        if any(item.startswith(prefix) for prefix in DUPLICATED_SOURCE_PREFIXES):
            violations.append(f"duplicated vendored source must not be tracked: {item}")

    for required in sorted(REQUIRED_FILES - tracked):
        violations.append(f"required module document is missing: {required}")

    return violations


def iter_strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from iter_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_strings(item)


def find_summary_violations(repo_root: Path) -> list[str]:
    violations: list[str] = []
    for summary_path in sorted(repo_root.glob(SUMMARY_GLOB)):
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            violations.append(f"invalid fixture summary {summary_path.relative_to(repo_root)}: {error}")
            continue
        for value in iter_strings(payload):
            if value.startswith(LOCAL_HOME_PREFIXES):
                relative = summary_path.relative_to(repo_root)
                violations.append(f"fixture summary contains local absolute path: {relative}")
                break
    return violations


def find_gitlink_violations(gitlinks: Mapping[str, str]) -> list[str]:
    violations: list[str] = []
    for path, expected in REQUIRED_GITLINKS.items():
        actual = gitlinks.get(path)
        if actual != expected:
            violations.append(
                f"submodule must stay on the reproducible upstream pin: {path} "
                f"expected={expected} actual={actual or 'missing'}"
            )
    return violations


def find_violations(repo_root: Path, paths: Iterable[str]) -> list[str]:
    return find_path_violations(paths) + find_summary_violations(repo_root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    violations = find_violations(repo_root, tracked_files(repo_root))
    violations.extend(find_gitlink_violations(tracked_gitlinks(repo_root)))
    if violations:
        for violation in violations:
            print(f"ERROR: {violation}")
        return 1
    print("repository layout: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
