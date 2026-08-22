#!/usr/bin/env python3
"""Verify that the packaged sherpa NAPI library can resolve its C API symbols."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


NAPI_MEMBER = "libs/arm64-v8a/libsherpa_onnx.so"
C_API_MEMBER = "libs/arm64-v8a/libsherpa-onnx-c-api.so"


def parse_dynamic_symbols(output: str) -> tuple[set[str], set[str]]:
    undefined: set[str] = set()
    defined: set[str] = set()
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 2 or not fields[0].startswith("SherpaOnnx"):
            continue
        symbol, symbol_type = fields[0], fields[1]
        if symbol_type.upper() == "U":
            undefined.add(symbol)
        else:
            defined.add(symbol)
    return undefined, defined


def find_llvm_nm() -> list[str]:
    configured = os.environ.get("LLVM_NM")
    if configured:
        return [configured]

    deveco_home = Path(
        os.environ.get("DEVECO_STUDIO_HOME", "/Applications/DevEco-Studio.app/Contents")
    )
    bundled = deveco_home / "sdk/default/openharmony/native/llvm/bin/llvm-nm"
    if bundled.is_file():
        return [str(bundled)]

    llvm_nm = shutil.which("llvm-nm")
    if llvm_nm:
        return [llvm_nm]

    xcrun = shutil.which("xcrun")
    if xcrun:
        probe = subprocess.run(
            [xcrun, "--find", "llvm-nm"],
            check=False,
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            return [xcrun, "llvm-nm"]

    raise RuntimeError("llvm-nm not found; install or configure the Harmony native toolchain")


def dynamic_symbols(path: Path, llvm_nm: list[str]) -> tuple[set[str], set[str]]:
    result = subprocess.run(
        [*llvm_nm, "--dynamic", "--format=posix", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"failed to inspect {path}: {detail}")
    return parse_dynamic_symbols(result.stdout)


def verify_pair(napi: Path, c_api: Path, llvm_nm: list[str]) -> set[str]:
    napi_undefined, _ = dynamic_symbols(napi, llvm_nm)
    _, c_api_defined = dynamic_symbols(c_api, llvm_nm)
    return napi_undefined - c_api_defined


def verify_hap(hap: Path, llvm_nm: list[str]) -> set[str]:
    with tempfile.TemporaryDirectory(prefix="amphion-native-abi-") as temp_dir:
        temp_root = Path(temp_dir)
        with zipfile.ZipFile(hap) as archive:
            names = set(archive.namelist())
            missing_members = sorted({NAPI_MEMBER, C_API_MEMBER} - names)
            if missing_members:
                raise RuntimeError(f"HAP missing native libraries: {missing_members}")
            napi = temp_root / "libsherpa_onnx.so"
            c_api = temp_root / "libsherpa-onnx-c-api.so"
            napi.write_bytes(archive.read(NAPI_MEMBER))
            c_api.write_bytes(archive.read(C_API_MEMBER))
        return verify_pair(napi, c_api, llvm_nm)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hap", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        missing = sorted(verify_hap(args.hap, find_llvm_nm()))
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        print(f"[ERROR] Harmony native ABI verification failed: {exc}", file=sys.stderr)
        return 1

    if missing:
        print(
            "[ERROR] packaged libsherpa-onnx-c-api.so does not provide symbols "
            f"required by libsherpa_onnx.so: {', '.join(missing)}",
            file=sys.stderr,
        )
        return 1

    print("[OK] packaged sherpa NAPI/C API symbols are compatible")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
