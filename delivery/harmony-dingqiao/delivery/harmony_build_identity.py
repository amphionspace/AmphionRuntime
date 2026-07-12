#!/usr/bin/env python3
"""Write and verify the source/artifact identity for a Harmony demo build."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
HAP = SCRIPT_DIR.parent / (
    "samples/dingqiao-demo/entry/build/default/outputs/default/"
    "dingqiao_demo-default-signed.hap"
)
ARTIFACT_DIRS = {
    "amphion_asr.har": REPO_ROOT / "asr/harmony/sdk/build/default/outputs/default",
    "amphion_police.har": REPO_ROOT / "asr/harmony/sdk-police/build/default/outputs/default",
    "amphion_dingqiao.har": REPO_ROOT / "asr/harmony/sdk-dingqiao/build/default/outputs/default",
    "sherpa_onnx.har": REPO_ROOT / (
        "third_party/sherpa-onnx/harmony-os/SherpaOnnxHar/sherpa_onnx/"
        "build/default/outputs/default"
    ),
}
MODEL_MANIFEST = REPO_ROOT / (
    "asr/harmony/sdk/src/main/resources/rawfile/amphion-models/manifest.json"
)
NATIVE_LIBRARIES = {
    "libsherpa-onnx-c-api.so": REPO_ROOT
    / "asr/harmony/sdk/src/main/cpp/libs/arm64-v8a/libsherpa-onnx-c-api.so",
    "libonnxruntime.so": REPO_ROOT
    / "asr/harmony/sdk/src/main/cpp/libs/arm64-v8a/libonnxruntime.so",
}
TRACKED_BUILD_INPUTS = (
    "asr/harmony",
    "delivery/harmony-dingqiao/samples",
    "delivery/harmony-dingqiao/AppScope",
    "delivery/harmony-dingqiao/build-profile.json5",
    "delivery/harmony-dingqiao/hvigor",
    "delivery/harmony-dingqiao/hvigorfile.ts",
    "delivery/harmony-dingqiao/oh-package.json5",
    "third_party/patches/sherpa-amphion",
)


class IdentityFailure(RuntimeError):
    pass


def run(command: list[str], *, cwd: Path = REPO_ROOT) -> bytes:
    return subprocess.run(command, cwd=cwd, check=True, stdout=subprocess.PIPE).stdout


def sha256_file(path: Path) -> str:
    if not path.is_file():
        raise IdentityFailure(f"missing build identity input: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sole_har(directory: Path) -> Path:
    candidates = sorted(path for path in directory.glob("*.har") if path.is_file())
    if len(candidates) != 1:
        raise IdentityFailure(f"expected one HAR in {directory}, found {len(candidates)}")
    return candidates[0]


def add_path(digest: "hashlib._Hash", relative: str, path: Path) -> None:
    digest.update(relative.encode("utf-8"))
    digest.update(b"\0")
    digest.update(path.read_bytes())
    digest.update(b"\0")


def source_fingerprint() -> str:
    digest = hashlib.sha256()
    tracked = run(["git", "ls-files", "-z", "--", *TRACKED_BUILD_INPUTS])
    for encoded in sorted(item for item in tracked.split(b"\0") if item):
        relative = encoded.decode("utf-8")
        path = REPO_ROOT / relative
        if path.is_file():
            add_path(digest, relative, path)

    submodule = REPO_ROOT / "third_party/sherpa-onnx"
    digest.update(run(["git", "rev-parse", "HEAD"], cwd=submodule).strip())
    digest.update(b"\0")
    digest.update(run(["git", "diff", "--binary", "HEAD"], cwd=submodule))
    untracked = run(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=submodule)
    for encoded in sorted(item for item in untracked.split(b"\0") if item):
        relative = encoded.decode("utf-8")
        if relative == ".amphion-patches-applied" or relative.startswith("build-"):
            continue
        path = submodule / relative
        if path.is_file():
            add_path(digest, f"third_party/sherpa-onnx/{relative}", path)
    return digest.hexdigest()


def current_identity() -> dict[str, object]:
    artifacts: dict[str, dict[str, object]] = {
        "dingqiao_demo.hap": {
            "path": str(HAP.relative_to(REPO_ROOT)),
            "sha256": sha256_file(HAP),
            "size_bytes": HAP.stat().st_size,
        }
    }
    for logical_name, directory in ARTIFACT_DIRS.items():
        path = sole_har(directory)
        artifacts[logical_name] = {
            "path": str(path.relative_to(REPO_ROOT)),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
    return {
        "schema_version": 1,
        "git_commit": run(["git", "rev-parse", "HEAD"]).decode().strip(),
        "source_fingerprint_sha256": source_fingerprint(),
        "model_manifest_sha256": sha256_file(MODEL_MANIFEST),
        "native_sha256": {
            name: sha256_file(path) for name, path in sorted(NATIVE_LIBRARIES.items())
        },
        "artifacts": artifacts,
    }


def write_identity(output: Path) -> None:
    identity = current_identity()
    identity["created_at"] = datetime.now(timezone.utc).isoformat()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(f"[OK] wrote Harmony build identity: {output}")


def verify_identity(identity_path: Path) -> None:
    try:
        recorded = json.loads(identity_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IdentityFailure(f"cannot read Harmony build identity: {error}") from error
    recorded.pop("created_at", None)
    current = current_identity()
    if recorded != current:
        raise IdentityFailure(
            "Harmony HAR/HAP build identity is stale; rerun build_install_smoke.sh before packaging"
        )
    print("[OK] Harmony HAR/HAP build identity matches current source and artifacts")


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", type=Path)
    group.add_argument("--verify", type=Path)
    args = parser.parse_args()
    try:
        if args.write is not None:
            write_identity(args.write)
        else:
            verify_identity(args.verify)
        return 0
    except (IdentityFailure, subprocess.SubprocessError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
