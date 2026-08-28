#!/usr/bin/env python3
"""Validate the final Android zh-en SDK-only delivery ZIP."""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from asr.tools.dingqiao_parameter_contract import (  # noqa: E402
    ParameterContractError,
    load_contract,
    validate_parameter_document,
)


# The current zh-en fat AAR is about 251 MiB. 320 MiB leaves model-growth headroom while
# still catching accidental APK/demo-source duplication, which previously produced a 1 GiB ZIP.
MAX_SDK_ONLY_ZIP_BYTES = 320 * 1024 * 1024
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_DOCS = {
    "docs/CHANGELOG.md",
    "docs/DINGQIAO_ASR_PARAMETER_CONTRACT.json",
    "docs/DINGQIAO_INTEGRATION.md",
    "docs/DINGQIAO_VOICEPRINT_MODEL.md",
    "docs/LICENSE.md",
    "docs/NOTICE",
    "docs/third-party/Apache-2.0.txt",
    "docs/third-party/WebRTC-BSD-3-Clause.txt",
    "docs/语音识别SDK接口.md",
}
REQUIRED_AAR_PREFIXES = {
    "jni/arm64-v8a/libamphion_audio_processing.so",
    "jni/arm64-v8a/libamphion_diarization_jni.so",
    "jni/arm64-v8a/libamphion_police_jni.so",
    "assets/amphion-models/zh-en/v1/",
    "assets/amphion-models/punct-zhen/v1/",
    "assets/amphion-models/itn-zh/v1/",
    "assets/amphion-models/vad/v1/",
    "assets/amphion-dingqiao/eres2net.onnx",
    "assets/amphion-dingqiao/pyannote-segmentation-3.0.onnx",
    "assets/lac/v1/lac_encoder.onnx",
    "assets/lac/v1/lac_crf_transitions.npy",
    "assets/police_terms/",
    "assets/police_station/",
    "assets/plate/plate_homophone.fst",
    "assets/plate/plate_homophones.csv",
    "assets/plate/plate_readings_v2.csv",
    "assets/plate/plate_spec_ga36.tsv",
}
TEXT_ASSET_SUFFIXES = {
    ".csv",
    ".json",
    ".json5",
    ".md",
    ".properties",
    ".tsv",
    ".txt",
}
LOCAL_PATH_PATTERNS = (
    re.compile(r"/(?:Users|home)/"),
    re.compile(r"[A-Za-z]:\\Users\\"),
)


class DeliveryValidationError(RuntimeError):
    pass


def _parse_properties(payload: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in payload.decode("utf-8").splitlines():
        if not raw or raw.startswith("#"):
            continue
        key, separator, value = raw.partition("=")
        if not separator:
            raise DeliveryValidationError(f"invalid VERSION.txt line: {raw}")
        values[key] = value
    return values


def _validate_checksums(
    archive: zipfile.ZipFile,
    root: str,
    files: set[str],
) -> None:
    checksum_name = f"{root}/CHECKSUMS.txt"
    expected_files = files - {"CHECKSUMS.txt"}
    checksums: dict[str, str] = {}
    for line_number, line in enumerate(
        archive.read(checksum_name).decode("utf-8").splitlines(), 1
    ):
        digest, separator, relative = line.partition("  ./")
        if not separator or not SHA256.fullmatch(digest):
            raise DeliveryValidationError(f"invalid checksum line {line_number}")
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts:
            raise DeliveryValidationError(f"unsafe checksum path: {relative}")
        normalized = path.as_posix()
        if normalized in checksums:
            raise DeliveryValidationError(f"duplicate checksum path: {normalized}")
        checksums[normalized] = digest
    if set(checksums) != expected_files:
        raise DeliveryValidationError("checksum file set does not match ZIP payload")
    for relative, expected in checksums.items():
        actual = hashlib.sha256(archive.read(f"{root}/{relative}")).hexdigest()
        if actual != expected:
            raise DeliveryValidationError(f"checksum mismatch: {relative}")


def _validate_aar(payload: bytes, expected_status: str) -> None:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        bad = archive.testzip()
        if bad:
            raise DeliveryValidationError(f"AAR CRC failed: {bad}")
        names = set(archive.namelist())
        manifest_name = "META-INF/amphion-dingqiao-build.properties"
        if manifest_name not in names:
            raise DeliveryValidationError("AAR missing delivery provenance manifest")
        manifest = _parse_properties(archive.read(manifest_name))
        if manifest.get("amphion.delivery.status") != expected_status:
            raise DeliveryValidationError(
                "AAR delivery status does not match VERSION.txt"
            )
        lowered = [name.lower() for name in names]
        forbidden = next(
            (
                name
                for name in lowered
                if "yue-en" in name
                or "zh-yue" in name
                or name.endswith("amphion-license.lic")
                or name.endswith("_meta.json")
            ),
            None,
        )
        if forbidden:
            raise DeliveryValidationError(f"forbidden AAR payload: {forbidden}")
        for required in REQUIRED_AAR_PREFIXES:
            if required.endswith("/"):
                present = any(
                    name.startswith(required) and name != required for name in names
                )
            else:
                present = required in names
            if not present:
                raise DeliveryValidationError(f"missing required AAR payload: {required}")
        for name in names:
            if PurePosixPath(name).suffix.lower() not in TEXT_ASSET_SUFFIXES:
                continue
            try:
                text = archive.read(name).decode("utf-8")
            except UnicodeDecodeError as error:
                raise DeliveryValidationError(f"AAR text asset is not UTF-8: {name}") from error
            if any(pattern.search(text) for pattern in LOCAL_PATH_PATTERNS):
                raise DeliveryValidationError(f"AAR exposes local build path: {name}")


def validate_delivery(zip_path: Path, version: str, *, preview: bool = False) -> None:
    if not zip_path.is_file():
        raise DeliveryValidationError(f"delivery ZIP not found: {zip_path}")
    if zip_path.stat().st_size > MAX_SDK_ONLY_ZIP_BYTES:
        raise DeliveryValidationError(
            f"SDK-only ZIP exceeds {MAX_SDK_ONLY_ZIP_BYTES} bytes: {zip_path.stat().st_size}"
        )
    with zipfile.ZipFile(zip_path) as archive:
        bad = archive.testzip()
        if bad:
            raise DeliveryValidationError(f"ZIP CRC failed: {bad}")
        all_names = archive.namelist()
        roots = {PurePosixPath(name).parts[0] for name in all_names if name}
        if len(roots) != 1:
            raise DeliveryValidationError("delivery ZIP must contain exactly one root directory")
        root = roots.pop()
        suffix = "-PREVIEW-NON-CANONICAL" if preview else ""
        expected_root = f"amphion-dingqiao-asr-sdk-v{version}-"
        if not re.fullmatch(
            rf"{re.escape(expected_root)}[0-9]{{8}}{re.escape(suffix)}", root
        ):
            raise DeliveryValidationError(
                f"delivery root must expose {'preview' if preview else 'formal'} identity"
            )
        if zip_path.stem != root:
            raise DeliveryValidationError("delivery ZIP filename must match its root identity")
        files = {
            PurePosixPath(name).relative_to(root).as_posix()
            for name in all_names
            if name and not name.endswith("/")
        }
        required = {
            "README.txt",
            "VERSION.txt",
            "CHECKSUMS.txt",
            f"aar/dingqiao-asr-v{version}{suffix}.aar",
            *REQUIRED_DOCS,
        }
        missing = sorted(required - files)
        if missing:
            raise DeliveryValidationError(f"missing SDK-only file: {missing[0]}")
        unexpected_top = sorted(
            relative
            for relative in files
            if PurePosixPath(relative).parts[0] not in {"aar", "docs"}
            and relative not in {"README.txt", "VERSION.txt", "CHECKSUMS.txt"}
        )
        if unexpected_top:
            raise DeliveryValidationError(f"unexpected top-level payload: {unexpected_top[0]}")
        forbidden = sorted(
            relative
            for relative in files
            if any(part.lower() in {"demo", "demo-src", "license", "tts", "tts-models"}
                   for part in PurePosixPath(relative).parts)
            or relative.lower().endswith((".apk", ".hap", ".lic"))
            or "yue-en" in relative.lower()
            or "zh-yue" in relative.lower()
        )
        if forbidden:
            raise DeliveryValidationError(f"forbidden SDK-only payload: {forbidden[0]}")
        aars = sorted(relative for relative in files if relative.endswith(".aar"))
        if aars != [f"aar/dingqiao-asr-v{version}{suffix}.aar"]:
            raise DeliveryValidationError("SDK-only delivery must contain exactly one versioned AAR")

        version_values = _parse_properties(archive.read(f"{root}/VERSION.txt"))
        expected_values = {
            "delivery_version": version,
            "sdk_version": version,
            "delivery_status": "PREVIEW / NON-CANONICAL" if preview else "FORMAL",
            "platform": "android",
            "language": "zh-en",
            "sdk_only": "true",
            "contains_demo": "false",
            "contains_tts": "false",
            "contains_license": "false",
        }
        for key, expected in expected_values.items():
            if version_values.get(key) != expected:
                raise DeliveryValidationError(
                    f"VERSION.txt {key}={version_values.get(key)!r}, expected {expected!r}"
                )
        readme = archive.read(f"{root}/README.txt").decode("utf-8")
        expected_status = "PREVIEW / NON-CANONICAL" if preview else "FORMAL"
        if f"交付状态：{expected_status}" not in readme:
            raise DeliveryValidationError("README missing explicit delivery status")
        for statement in (
            "SDK-only",
            "警务文本增强",
            "默认开启",
            "按会话关闭",
            "不包含粤英模型",
            "Demo APK",
            "授权文件",
        ):
            if statement not in readme:
                raise DeliveryValidationError(f"README missing delivery boundary: {statement}")
        embedded_contract = load_contract(
            archive.read(f"{root}/docs/DINGQIAO_ASR_PARAMETER_CONTRACT.json")
        )
        if embedded_contract != load_contract():
            raise DeliveryValidationError(
                "embedded Dingqiao parameter contract does not match current source"
            )
        validate_parameter_document(
            archive.read(f"{root}/docs/语音识别SDK接口.md").decode("utf-8"),
            embedded_contract,
        )
        _validate_checksums(archive, root, files)
        _validate_aar(
            archive.read(f"{root}/{aars[0]}"),
            "preview-non-canonical" if preview else "formal",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--preview",
        action="store_true",
        help="require PREVIEW / NON-CANONICAL identity at every artifact layer",
    )
    args = parser.parse_args()
    try:
        validate_delivery(args.zip_path, args.version, preview=args.preview)
    except (
        DeliveryValidationError,
        OSError,
        ParameterContractError,
        UnicodeError,
        zipfile.BadZipFile,
    ) as error:
        raise SystemExit(f"[ERROR] {error}") from error
    print(f"[OK] Android zh-en SDK-only delivery validated: {args.zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
