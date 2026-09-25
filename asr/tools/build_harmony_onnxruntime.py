#!/usr/bin/env python3
"""Build the pinned OHOS runtime used by the ASR SDK (including bounded worker spin)."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import zipfile


REPO = Path(__file__).resolve().parents[2]
ORT_COMMIT = "2ac381c55397dffff327cc6efecf6f95a70f90a1"  # v1.16.3
EIGEN_COMMIT = "e7248b26a1ed53fa030c5c459f7ea095dfd276ac"
PATCH = REPO / "third_party/patches/onnxruntime-amphion/0001-ohos-bounded-worker-spin.patch"
FLAGS = REPO / "asr/tools/harmony_onnxruntime_flags.cmake"


def run(*args, cwd=None, capture=False):
    return subprocess.run(
        [str(arg) for arg in args], cwd=cwd, check=True,
        env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"},
        stdout=subprocess.PIPE if capture else None,
    ).stdout


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checkout(path, url, commit):
    if not (path / ".git").exists():
        path.mkdir(parents=True, exist_ok=True)
        run("git", "init", path)
        run("git", "remote", "add", "origin", url, cwd=path)
        run("git", "fetch", "--depth", "1", "origin", commit, cwd=path)
        run("git", "checkout", "--detach", "FETCH_HEAD", cwd=path)
    actual = run("git", "rev-parse", "HEAD", cwd=path, capture=True).decode().strip()
    if actual != commit:
        raise RuntimeError(f"Unexpected source revision at {path}: {actual}")


def source_diff(source):
    return run("git", "diff", "--binary", "HEAD", cwd=source, capture=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sdk_value = os.environ.get("OHOS_SDK_NATIVE_DIR")
    if not sdk_value:
        parser.error("Source asr/tools/harmony_env.sh or run asr/tools/04_build_harmony_so.sh first")
    sdk = Path(sdk_value).resolve()
    patch_hash = sha256(PATCH)
    root = Path(os.environ.get("AMPHION_ORT_OHOS_ROOT", str(
        REPO / "third_party/.derived" / f"onnxruntime-ohos-1.16.3-{patch_hash[:12]}"))).resolve()
    source = root / "source"
    build = Path(os.environ.get("AMPHION_ORT_OHOS_BUILD_DIR", str(root / "build"))).resolve()
    checkout(source, "https://github.com/microsoft/onnxruntime.git", ORT_COMMIT)
    if not source_diff(source):
        run("git", "apply", PATCH, cwd=source)
    if source_diff(source) != PATCH.read_bytes():
        raise RuntimeError(f"ORT source differs from the approved patch; preserve and inspect {source}")
    run("git", "submodule", "update", "--init", "--depth", "1", "cmake/external/onnx", cwd=source)

    # The old Eigen archive has changed bytes upstream. Use its exact pinned Git
    # revision instead of accepting a different archive checksum or dependency.
    eigen = root / "eigen-pinned"
    checkout(eigen, "https://gitlab.com/libeigen/eigen.git", EIGEN_COMMIT)
    if source_diff(eigen):
        raise RuntimeError(f"Modified Eigen source: {eigen}")

    host = (platform.system(), platform.machine().lower())
    protoc_key = {
        ("Darwin", "arm64"): "protoc_mac_universal",
        ("Darwin", "x86_64"): "protoc_mac_universal",
        ("Linux", "x86_64"): "protoc_linux_x64",
        ("Linux", "aarch64"): "protoc_linux_aarch64",
    }.get(host)
    if protoc_key is None:
        raise RuntimeError(f"Unsupported build host: {host}")
    dependency = next(line.split(";") for line in (source / "cmake/deps.txt").read_text().splitlines()
                      if line.startswith(protoc_key + ";"))
    archive = root / dependency[1].rsplit("/", 1)[1]
    if not archive.exists():
        run("curl", "--fail", "--location", "--output", archive, dependency[1])
    if hashlib.sha1(archive.read_bytes()).hexdigest() != dependency[2]:
        raise RuntimeError(f"Host protoc checksum differs from pinned ORT dependency: {archive}")
    protoc_root = root / "host-protoc"
    with zipfile.ZipFile(archive) as package:
        package.extractall(protoc_root)
    protoc = protoc_root / "bin/protoc"
    protoc.chmod(0o755)

    # The publisher builds this release as Linux with the standalone OHOS
    # sysroot. Keep the installed toolchain untouched and use a local wrapper.
    wrapper = root / "ohos-linux-wrapper.cmake"
    wrapper.write_text(
        f'include("{sdk}/build/cmake/ohos.toolchain.cmake")\n'
        "set(CMAKE_SYSTEM_NAME Linux)\nset(CMAKE_SYSTEM_PROCESSOR aarch64)\n"
        "unset(CMAKE_C_COMPILER_EXTERNAL_TOOLCHAIN)\n"
        "unset(CMAKE_CXX_COMPILER_EXTERNAL_TOOLCHAIN)\n"
        "unset(CMAKE_ASM_COMPILER_EXTERNAL_TOOLCHAIN)\n")
    cmake = sdk / "build-tools/cmake/bin/cmake"
    run(cmake, "-S", source / "cmake", "-B", build, "-C", FLAGS,
        f"-DCMAKE_TOOLCHAIN_FILE={wrapper}", "-DCMAKE_BUILD_TYPE=Release", "-DOHOS_ARCH=arm64-v8a",
        "-DCMAKE_TLS_VERIFY=ON", "-DFETCHCONTENT_QUIET=OFF",
        "-Donnxruntime_USE_PREINSTALLED_EIGEN=ON", f"-Deigen_SOURCE_PATH={eigen}",
        f"-DPYTHON_EXECUTABLE={sys.executable}", f"-DONNX_CUSTOM_PROTOC_EXECUTABLE={protoc}",
        "-Dprotobuf_BUILD_PROTOC_BINARIES=OFF", "-DFLATBUFFERS_BUILD_FLATC=OFF")
    run(cmake, "--build", build, "--target", "onnxruntime", "--parallel", "4")
    if source_diff(source) != PATCH.read_bytes():
        raise RuntimeError("ORT source changed during the build")
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    # Hvigor also uses full strip. Normalize before packaging so the existing
    # exact local-library/HAP identity check remains meaningful and unchanged.
    run(sdk / "llvm/bin/llvm-strip", "--strip-all", "-o", output, build / "libonnxruntime.so")
    provenance = {
        "runtimeVersion": "1.16.3", "sourceCommit": ORT_COMMIT,
        "patchSha256": patch_hash, "flagsSha256": sha256(FLAGS), "eigenCommit": EIGEN_COMMIT,
        "protocArchiveSha256": sha256(archive), "librarySha256": sha256(output),
        "compiler": run(sdk / "llvm/bin/clang++", "--version", capture=True).decode().strip(),
        "workerSpinLog2": 14,
    }
    output.with_suffix(".provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    main()
