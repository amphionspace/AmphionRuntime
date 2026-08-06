#!/usr/bin/env python3
"""Validate the public zh-en Harmony ASR SDK-only delivery layout."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tarfile
import tempfile
import zipfile


MODEL_MD5_POLICY_PATH = Path(__file__).with_name("dingqiao_zh_en_model_md5.json")
TARGET_SPEAKER_METADATA_PATH = Path(__file__).with_name("convtasnet_16k_ort.json")
MAX_SDK_ONLY_ZIP_BYTES = 320 * 1024 * 1024
RUNTIME_IDENTITY_SOURCE_PATH = (
    Path(__file__).resolve().parents[3]
    / "asr/harmony/sdk/src/main/ets/com/amphion/asr/RuntimeIdentity.ts"
)
PINNED_MODEL_ONNX_SOURCES = {
    "decoder.onnx",
    "encoder.int8.onnx",
    "joiner.onnx",
}
MODEL_MANIFEST_PATH = (
    "package/_bundled/amphion_asr/src/main/resources/rawfile/"
    "amphion-models/manifest.json"
)
TARGET_SPEAKER_MODEL_PATH = (
    "package/src/main/resources/rawfile/amphion-dingqiao/convtasnet_16k.ort"
)
VERSIONED_PACKAGE_PATHS = (
    "package/_bundled/amphion_asr/oh-package.json5",
    "package/_bundled/amphion_asr/src/main/cpp/types/libamphion_asr/oh-package.json5",
)
RUNTIME_IDENTITY_PATH = (
    "package/_bundled/amphion_asr/src/main/ets/com/amphion/asr/RuntimeIdentity.ts"
)
POLICE_PACKAGE_PATH = "package/_bundled/amphion_police/oh-package.json5"
POLICE_ASSET_ROOT = PurePosixPath(
    "package/_bundled/amphion_police/src/main/resources/rawfile/amphion-police"
)
POLICE_MANIFEST_PATH = (POLICE_ASSET_ROOT / "manifest.json").as_posix()
ALLOWED_MODEL_BUNDLES = {
    "zh-en/v1",
    "punct-zhen/v1",
    "itn-zh/v1",
    "vad/v1",
}
REQUIRED_FILES = {
    "README.md",
    "har/amphion_dingqiao.har",
    "docs/LICENSE.md",
    "docs/LICENSE_SCHEME.md",
    "docs/CHANGELOG.md",
    "docs/TROUBLESHOOTING.md",
    "docs/ASR_LIFECYCLE_ASSURANCE_20260716.md",
    "docs/ASR_LIFECYCLE_ASSURANCE_EVIDENCE_20260716.json",
    "docs/INTEGRATION.md",
    "docs/PRIVACY.md",
    "docs/NOTICE",
    "docs/SDK_LIFECYCLE_PERFORMANCE_SUMMARY_20260713.md",
    "docs/ASR_SDK_API_HARMONY.md",
    "docs/third-party/ONNX-Runtime-MIT.txt",
    "docs/third-party/Apache-2.0.txt",
    "docs/BUILD_PROVENANCE.json",
    "docs/checksum.txt",
}
CHECKSUM_RE = re.compile(r"^([0-9a-f]{64})  \./(.+)$")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
FORBIDDEN_HAR_SUFFIXES = {
    ".jks", ".key", ".keystore", ".lic", ".p12", ".pem", ".pfx"
}
HAR_TEXT_SUFFIXES = {
    "", ".csv", ".ets", ".json", ".json5", ".md", ".ts", ".tsv", ".txt", ".vocab"
}
HAR_TEXT_PATTERNS = (
    ("local user home path", re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\Users\\)")),
    ("macOS temporary path", re.compile(r"/var/folders/")),
    ("private key material", re.compile(r"-----BEGIN (?:EC |RSA )?PRIVATE KEY-----")),
    ("internal stress run identifier", re.compile(r"\b20\d{6}-\d{6}-[a-z0-9-]+-[0-9a-f]{8}\b")),
)


class DeliveryValidationError(RuntimeError):
    pass


def _load_expected_runtime_identity() -> dict[str, str]:
    try:
        source = RUNTIME_IDENTITY_SOURCE_PATH.read_text(encoding="utf-8")
    except OSError as error:
        raise DeliveryValidationError(
            f"cannot read runtime identity source: {RUNTIME_IDENTITY_SOURCE_PATH}"
        ) from error
    patterns = {
        "version": r"HARMONY_SDK_VERSION: string = '([^']+)'",
        "major": r"HARMONY_SDK_MAJOR: number = ([0-9]+)",
        "release_date": r"HARMONY_SDK_RELEASE_DATE: string = '([0-9]{4}-[0-9]{2}-[0-9]{2})'",
    }
    identity: dict[str, str] = {}
    for field, pattern in patterns.items():
        match = re.search(pattern, source)
        if match is None:
            raise DeliveryValidationError(f"runtime identity source is missing {field}")
        identity[field] = match.group(1)
    return identity


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_pinned_model_md5() -> dict[str, str]:
    try:
        policy = json.loads(MODEL_MD5_POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DeliveryValidationError("pinned model identity policy is invalid") from error
    if not isinstance(policy, dict) or policy.get("schema_version") != 3:
        raise DeliveryValidationError("unsupported pinned model identity policy")
    model_id = policy.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        raise DeliveryValidationError("pinned model identity policy has no model_id")
    expected = policy.get("onnx_files_md5")
    if not isinstance(expected, dict) or not expected:
        raise DeliveryValidationError("pinned model identity policy has no source files")
    for relative, digest in expected.items():
        if not isinstance(relative, str):
            raise DeliveryValidationError("invalid pinned model ONNX MD5 entry")
        path = PurePosixPath(relative)
        if (
            path.is_absolute()
            or ".." in path.parts
            or path.name != relative
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{32}", digest) is None
        ):
            raise DeliveryValidationError(f"invalid pinned model ONNX MD5 entry: {relative}")
    if set(expected) != PINNED_MODEL_ONNX_SOURCES:
        missing = sorted(PINNED_MODEL_ONNX_SOURCES - set(expected))
        extra = sorted(set(expected) - PINNED_MODEL_ONNX_SOURCES)
        detail = missing[0] if missing else extra[0]
        raise DeliveryValidationError(f"pinned model ONNX file set mismatch: {detail}")
    return expected


def _load_pinned_target_speaker_identity() -> dict[str, object]:
    try:
        metadata = json.loads(TARGET_SPEAKER_METADATA_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DeliveryValidationError(
            "target-speaker ORT identity metadata is invalid"
        ) from error
    identity = {
        "path": TARGET_SPEAKER_MODEL_PATH,
        "format": metadata.get("format"),
        "size_bytes": metadata.get("output_size_bytes"),
        "sha256": metadata.get("output_sha256"),
        "converter_id": metadata.get("converter_id"),
        "source_name": metadata.get("source_name"),
        "source_sha256": metadata.get("source_sha256"),
    }
    if identity["format"] != "ort":
        raise DeliveryValidationError("target-speaker model format must be ort")
    if identity["converter_id"] != "onnxruntime-1.16.3-fixed-arm-cpu-v1":
        raise DeliveryValidationError("target-speaker ORT converter identity mismatch")
    if not isinstance(identity["size_bytes"], int) or identity["size_bytes"] <= 0:
        raise DeliveryValidationError("target-speaker ORT size identity is invalid")
    for field in ("sha256", "source_sha256"):
        if not isinstance(identity[field], str) or re.fullmatch(
            r"[0-9a-f]{64}", identity[field]
        ) is None:
            raise DeliveryValidationError(f"target-speaker ORT {field} is invalid")
    if identity["source_name"] != "convtasnet_16k.onnx":
        raise DeliveryValidationError("target-speaker ORT source identity mismatch")
    return identity


def _validate_layout(root: Path) -> None:
    if not root.is_dir():
        raise DeliveryValidationError(f"delivery directory does not exist: {root}")
    symlinks = [path for path in root.rglob("*") if path.is_symlink()]
    if symlinks:
        raise DeliveryValidationError(f"delivery must not contain symlinks: {symlinks[0]}")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    missing = sorted(REQUIRED_FILES - actual)
    unexpected = sorted(actual - REQUIRED_FILES)
    if missing:
        raise DeliveryValidationError(f"missing required file: {missing[0]}")
    if unexpected:
        raise DeliveryValidationError(f"unexpected file in SDK-only delivery: {unexpected[0]}")


def _validate_checksums(root: Path) -> None:
    expected_files = REQUIRED_FILES - {"docs/checksum.txt"}
    checksums = {}
    for line_number, raw_line in enumerate(
        (root / "docs/checksum.txt").read_text(encoding="utf-8").splitlines(), 1
    ):
        match = CHECKSUM_RE.fullmatch(raw_line)
        if match is None:
            raise DeliveryValidationError(f"invalid checksum line {line_number}")
        digest, relative = match.groups()
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts:
            raise DeliveryValidationError(f"unsafe checksum path: {relative}")
        if relative in checksums:
            raise DeliveryValidationError(f"duplicate checksum path: {relative}")
        checksums[relative] = digest
    if set(checksums) != expected_files:
        missing = sorted(expected_files - set(checksums))
        extra = sorted(set(checksums) - expected_files)
        detail = missing[0] if missing else extra[0]
        raise DeliveryValidationError(f"checksum file set mismatch: {detail}")
    for relative, expected in checksums.items():
        actual = sha256(root / relative)
        if actual != expected:
            raise DeliveryValidationError(f"checksum mismatch: {relative}")


def _read_tar_json(archive: tarfile.TarFile, name: str) -> dict:
    try:
        member = archive.getmember(name)
    except KeyError as error:
        raise DeliveryValidationError(f"HAR missing required member: {name}") from error
    stream = archive.extractfile(member)
    if stream is None:
        raise DeliveryValidationError(f"HAR member is not a file: {name}")
    try:
        value = json.loads(stream.read())
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DeliveryValidationError(f"HAR member is not valid JSON: {name}") from error
    if not isinstance(value, dict):
        raise DeliveryValidationError(f"HAR JSON member must be an object: {name}")
    return value


def _read_tar_bytes(archive: tarfile.TarFile, name: str) -> bytes:
    try:
        member = archive.getmember(name)
    except KeyError as error:
        raise DeliveryValidationError(f"HAR missing required member: {name}") from error
    stream = archive.extractfile(member)
    if stream is None:
        raise DeliveryValidationError(f"HAR member is not a file: {name}")
    return stream.read()


def _validate_member_policy(archive: tarfile.TarFile) -> set[str]:
    names = set()
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise DeliveryValidationError(f"unsafe HAR member path: {member.name}")
        if member.name in names:
            raise DeliveryValidationError(f"duplicate HAR member: {member.name}")
        names.add(member.name)
        if not member.isfile() and not member.isdir():
            raise DeliveryValidationError(f"HAR contains link or special member: {member.name}")
        if (
            member.uid != 0
            or member.gid != 0
            or member.uname != ""
            or member.gname != ""
            or member.mtime != 0
            or member.pax_headers
        ):
            raise DeliveryValidationError(f"HAR member metadata is not normalized: {member.name}")
        if any(
            part.startswith("amphion-models") and part != "amphion-models"
            for part in path.parts
        ):
            raise DeliveryValidationError(f"unexpected model root in HAR: {member.name}")
        if any(part == ".DS_Store" or part.startswith("._") for part in path.parts):
            raise DeliveryValidationError(f"metadata file leaked into HAR: {member.name}")
        forbidden = (
            path.suffix.lower() in FORBIDDEN_HAR_SUFFIXES
            or "tests" in path.parts
            or path.name in {"CONTRACT_TESTS.md", "oh-package-lock.json5", "README.md"}
            or path.name.endswith("_meta.json")
        )
        if forbidden:
            raise DeliveryValidationError(f"forbidden HAR member: {member.name}")
        if member.isfile() and (
            path.suffix.lower() in HAR_TEXT_SUFFIXES or path.name in {"LICENSE", "NOTICE"}
        ):
            payload = _read_tar_bytes(archive, member.name)
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as error:
                raise DeliveryValidationError(
                    f"HAR text member is not UTF-8: {member.name}"
                ) from error
            for label, pattern in HAR_TEXT_PATTERNS:
                if pattern.search(text):
                    raise DeliveryValidationError(f"HAR {label}: {member.name}")
    return names


def _validate_har(
    root: Path,
    expected_version: str,
    expected_model_md5: dict[str, str],
    expected_identity: dict[str, str],
    expected_target_speaker: dict[str, object],
) -> dict:
    har_path = root / "har/amphion_dingqiao.har"
    try:
        archive = tarfile.open(har_path, "r:gz")
    except (tarfile.TarError, OSError) as error:
        raise DeliveryValidationError(f"invalid HAR archive: {har_path}") from error
    with archive:
        names = _validate_member_policy(archive)
        forbidden = sorted(name for name in names if "yue-en" in name.lower())
        if forbidden:
            raise DeliveryValidationError(f"HAR contains Yue model content: {forbidden[0]}")

        metadata = _read_tar_json(archive, "package/oh-package.json5")
        if metadata.get("version") != expected_version:
            raise DeliveryValidationError(
                f"HAR version {metadata.get('version')} != {expected_version}"
            )
        for path in VERSIONED_PACKAGE_PATHS:
            nested = _read_tar_json(archive, path)
            if nested.get("version") != expected_version:
                raise DeliveryValidationError(
                    f"nested HAR version {nested.get('version')} != {expected_version}: {path}"
                )
        dependencies = metadata.get("dependencies")
        if not isinstance(dependencies, dict) or dependencies.get("amphion_police") != \
                "file:./_bundled/amphion_police":
            raise DeliveryValidationError("HAR does not link bundled police enhancement")
        police_metadata = _read_tar_json(archive, POLICE_PACKAGE_PATH)
        if police_metadata.get("version") != expected_version:
            raise DeliveryValidationError(
                f"bundled police enhancement version {police_metadata.get('version')} "
                f"!= {expected_version}"
            )
        police_dependencies = police_metadata.get("dependencies")
        if not isinstance(police_dependencies, dict) or police_dependencies.get("amphion_asr") != \
                "file:../amphion_asr":
            raise DeliveryValidationError("bundled police enhancement does not link bundled ASR")
        for required_police_member in (
            "package/_bundled/amphion_police/Index.ets",
            "package/_bundled/amphion_police/src/main/ets/com/amphion/police/PoliceEnhancePipeline.ets",
        ):
            _read_tar_bytes(archive, required_police_member)

        police_manifest = _read_tar_json(archive, POLICE_MANIFEST_PATH)
        police_files = police_manifest.get("files")
        if not isinstance(police_files, dict) or not police_files:
            raise DeliveryValidationError("police enhancement manifest has no assets")
        expected_police_assets = {POLICE_MANIFEST_PATH}
        for relative, expected_hash in police_files.items():
            if not isinstance(relative, str) or not isinstance(expected_hash, str):
                raise DeliveryValidationError("invalid police enhancement manifest entry")
            relative_path = PurePosixPath(relative)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise DeliveryValidationError(
                    f"unsafe police enhancement asset path: {relative}"
                )
            asset_path = (POLICE_ASSET_ROOT / relative_path).as_posix()
            expected_police_assets.add(asset_path)
            payload = _read_tar_bytes(archive, asset_path)
            if hashlib.sha256(payload).hexdigest() != expected_hash:
                raise DeliveryValidationError(
                    f"police enhancement asset hash mismatch: {asset_path}"
                )
        actual_police_assets = {
            member.name
            for member in archive.getmembers()
            if member.isfile() and member.name.startswith(f"{POLICE_ASSET_ROOT.as_posix()}/")
        }
        if actual_police_assets != expected_police_assets:
            extra = sorted(actual_police_assets - expected_police_assets)
            missing = sorted(expected_police_assets - actual_police_assets)
            detail = extra[0] if extra else missing[0]
            raise DeliveryValidationError(
                f"police enhancement asset file set mismatch: {detail}"
            )
        identity = _read_tar_bytes(archive, RUNTIME_IDENTITY_PATH).decode("utf-8")
        expected_identity_tokens = (
            f"HARMONY_SDK_VERSION: string = '{expected_version}'",
            f"HARMONY_SDK_MAJOR: number = {expected_identity['major']}",
            f"HARMONY_SDK_RELEASE_DATE: string = '{expected_identity['release_date']}'",
        )
        if any(value not in identity for value in expected_identity_tokens):
            raise DeliveryValidationError("HAR runtime identity does not match release")

        target_speaker = _read_tar_bytes(archive, TARGET_SPEAKER_MODEL_PATH)
        if len(target_speaker) != expected_target_speaker.get("size_bytes"):
            raise DeliveryValidationError("target-speaker ORT size mismatch")
        if hashlib.sha256(target_speaker).hexdigest() != expected_target_speaker.get("sha256"):
            raise DeliveryValidationError("target-speaker ORT hash mismatch")

        manifest_payload = _read_tar_bytes(archive, MODEL_MANIFEST_PATH)
        try:
            manifest = json.loads(manifest_payload)
        except json.JSONDecodeError as error:
            raise DeliveryValidationError("HAR model manifest is invalid") from error
        bundles = manifest.get("bundles")
        if not isinstance(bundles, dict) or set(bundles) != ALLOWED_MODEL_BUNDLES:
            found = sorted(bundles) if isinstance(bundles, dict) else bundles
            raise DeliveryValidationError(f"unexpected model bundles: {found}")
        model_root = PurePosixPath(MODEL_MANIFEST_PATH).parent
        expected_model_files = {MODEL_MANIFEST_PATH}
        for bundle, entries in bundles.items():
            if not isinstance(entries, list):
                raise DeliveryValidationError(f"model bundle must be a list: {bundle}")
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                    raise DeliveryValidationError(f"invalid model entry in bundle: {bundle}")
                expected_path = (model_root / bundle / entry["name"]).as_posix()
                expected_model_files.add(expected_path)
                if expected_path not in names:
                    raise DeliveryValidationError(f"HAR missing model asset: {expected_path}")
                member = archive.getmember(expected_path)
                expected_size = entry.get("size_bytes")
                if not isinstance(expected_size, int) or member.size != expected_size:
                    raise DeliveryValidationError(f"model asset size mismatch: {expected_path}")
                expected_hash = entry.get("output_sha256")
                if not isinstance(expected_hash, str) or not re.fullmatch(
                    r"[0-9a-f]{64}", expected_hash
                ):
                    raise DeliveryValidationError(f"invalid model asset hash: {expected_path}")
                stream = archive.extractfile(member)
                if stream is None:
                    raise DeliveryValidationError(f"HAR model asset is not a file: {expected_path}")
                digest = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                if digest.hexdigest() != expected_hash:
                    raise DeliveryValidationError(f"model asset hash mismatch: {expected_path}")
        actual_model_files = {
            member.name
            for member in archive.getmembers()
            if member.isfile() and member.name.startswith(f"{model_root.as_posix()}/")
        }
        if actual_model_files != expected_model_files:
            extra = sorted(actual_model_files - expected_model_files)
            missing = sorted(expected_model_files - actual_model_files)
            detail = extra[0] if extra else missing[0]
            raise DeliveryValidationError(f"model asset file set mismatch: {detail}")
        zh_entries = bundles["zh-en/v1"]
        actual_sources = {}
        for entry in zh_entries:
            source_name = entry.get("source_name")
            if not isinstance(source_name, str):
                continue
            if source_name not in expected_model_md5:
                continue
            source_md5 = entry.get("source_md5")
            if not isinstance(source_md5, str):
                raise DeliveryValidationError("ZH_EN manifest lacks ONNX MD5 identity")
            if source_name in actual_sources:
                raise DeliveryValidationError(f"duplicate ZH_EN model source: {source_name}")
            actual_sources[source_name] = source_md5
        if set(actual_sources) != set(expected_model_md5):
            raise DeliveryValidationError("pinned ZH_EN ONNX file set mismatch")
        for source_name, approved_md5 in expected_model_md5.items():
            if actual_sources[source_name] != approved_md5:
                raise DeliveryValidationError(
                    f"model ONNX MD5 mismatch: {source_name}: "
                    f"{actual_sources[source_name]} != {approved_md5}"
                )
        return {
            "manifest_sha256": hashlib.sha256(manifest_payload).hexdigest(),
            "manifest_version": manifest.get("manifest_version"),
            "bundles": sorted(bundles),
            "onnx_md5": dict(sorted(actual_sources.items())),
            "target_speaker_separator": dict(expected_target_speaker),
        }


def _validate_provenance(root: Path, expected_version: str, har_evidence: dict) -> None:
    try:
        provenance = json.loads(
            (root / "docs/BUILD_PROVENANCE.json").read_text(encoding="utf-8")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DeliveryValidationError("BUILD_PROVENANCE.json is invalid") from error
    if provenance.get("delivery_version") != expected_version:
        raise DeliveryValidationError("provenance delivery version mismatch")
    if provenance.get("sdk_only") is not True:
        raise DeliveryValidationError("provenance must declare sdk_only=true")
    if provenance.get("asr_only") is not True:
        raise DeliveryValidationError("SDK-only ASR provenance must declare asr_only=true")
    if provenance.get("languages") != ["zh-en"]:
        raise DeliveryValidationError("provenance languages must be exactly ['zh-en']")
    if provenance.get("capabilities") != [
        "asr",
        "voiceprint",
        "punctuation",
        "itn",
        "vad",
        "industry-text-enhancement",
        "target-speaker-enhancement",
    ]:
        raise DeliveryValidationError("provenance capabilities do not match bundled SDK features")
    if provenance.get("excluded_capabilities") != []:
        raise DeliveryValidationError("provenance incorrectly excludes a bundled capability")
    artifacts = provenance.get("artifacts")
    if not isinstance(artifacts, list) or [item.get("path") for item in artifacts] != [
        "har/amphion_dingqiao.har"
    ]:
        raise DeliveryValidationError("provenance must contain exactly the ASR HAR artifact")
    artifact = artifacts[0]
    har_path = root / "har/amphion_dingqiao.har"
    if artifact.get("size_bytes") != har_path.stat().st_size:
        raise DeliveryValidationError("provenance HAR size mismatch")
    if artifact.get("sha256") != sha256(har_path):
        raise DeliveryValidationError("provenance HAR hash mismatch")
    model = provenance.get("model")
    if not isinstance(model, dict):
        raise DeliveryValidationError("provenance model evidence is missing")
    for field in (
        "manifest_sha256",
        "manifest_version",
        "bundles",
        "onnx_md5",
        "target_speaker_separator",
    ):
        if model.get(field) != har_evidence[field]:
            raise DeliveryValidationError(f"provenance model {field} mismatch")
    if "verified_build_identity" in provenance:
        raise DeliveryValidationError("SDK-only provenance exposes intermediate build artifacts")
    source = provenance.get("source")
    if isinstance(source, dict) and source.get("worktree_dirty") is not False:
        raise DeliveryValidationError("release provenance must declare a clean worktree")


def _validate_documents(root: Path) -> None:
    api = (root / "docs/ASR_SDK_API_HARMONY.md").read_text(encoding="utf-8")
    if any(value in api for value in ("zh-yue", "zh_yue")):
        raise DeliveryValidationError("SDK-only API document still advertises Yue")
    readme = (root / "README.md").read_text(encoding="utf-8")
    if not all(value in readme for value in ("不包含", "独立 TTS SDK", "TTS 模型")):
        raise DeliveryValidationError("README does not state the SDK-only TTS boundary")
    for statement in ("警务文本增强", "enablePoliceEnhancement", "不包含", "授权文件"):
        if statement not in readme:
            raise DeliveryValidationError(
                f"README does not match SDK-only capability boundary: {statement}"
            )
    for markdown in root.rglob("*.md"):
        text = markdown.read_text(encoding="utf-8")
        if "鼎桥" in text:
            raise DeliveryValidationError(
                f"customer-facing document contains excluded branding: {markdown}"
            )
        for raw_target in MARKDOWN_LINK_RE.findall(text):
            target = raw_target.strip().strip("<>").split("#", 1)[0]
            if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
                continue
            if target.startswith("/"):
                raise DeliveryValidationError(f"absolute Markdown link: {markdown}")
            resolved = (markdown.parent / target).resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError as error:
                raise DeliveryValidationError(f"Markdown link escapes delivery: {markdown}") from error
            if not resolved.exists():
                raise DeliveryValidationError(
                    f"broken Markdown link in {markdown.relative_to(root)}: {target}"
                )


def validate_delivery(
    root: Path,
    expected_version: str,
    expected_model_md5: dict[str, str] | None = None,
    expected_target_speaker: dict[str, object] | None = None,
) -> None:
    if expected_model_md5 is None:
        expected_model_md5 = _load_pinned_model_md5()
    if expected_target_speaker is None:
        expected_target_speaker = _load_pinned_target_speaker_identity()
    expected_identity = _load_expected_runtime_identity()
    if expected_identity["version"] != expected_version:
        raise DeliveryValidationError(
            f"runtime identity source version {expected_identity['version']} != {expected_version}"
        )
    _validate_layout(root)
    _validate_checksums(root)
    har_evidence = _validate_har(
        root,
        expected_version,
        expected_model_md5,
        expected_identity,
        expected_target_speaker,
    )
    _validate_provenance(root, expected_version, har_evidence)
    _validate_documents(root)


def validate_delivery_path(
    path: Path,
    expected_version: str,
    expected_model_md5: dict[str, str] | None = None,
    expected_target_speaker: dict[str, object] | None = None,
) -> None:
    if path.is_dir():
        validate_delivery(
            path, expected_version, expected_model_md5, expected_target_speaker
        )
        return
    if not path.is_file() or path.suffix.lower() != ".zip":
        raise DeliveryValidationError(f"delivery must be a directory or final ZIP: {path}")
    if path.stat().st_size > MAX_SDK_ONLY_ZIP_BYTES:
        raise DeliveryValidationError(
            f"SDK-only ZIP exceeds {MAX_SDK_ONLY_ZIP_BYTES} bytes: {path.stat().st_size}"
        )
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as error:
        raise DeliveryValidationError(f"invalid delivery ZIP: {path}") from error
    with archive, tempfile.TemporaryDirectory() as directory:
        bad = archive.testzip()
        if bad is not None:
            raise DeliveryValidationError(f"delivery ZIP CRC failed: {bad}")
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise DeliveryValidationError("delivery ZIP contains duplicate member names")
        roots: set[str] = set()
        destination = Path(directory)
        for info in infos:
            if "\\" in info.filename:
                raise DeliveryValidationError(f"unsafe ZIP member path: {info.filename}")
            member = PurePosixPath(info.filename)
            if member.is_absolute() or ".." in member.parts or not member.parts:
                raise DeliveryValidationError(f"unsafe ZIP member path: {info.filename}")
            roots.add(member.parts[0])
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise DeliveryValidationError(f"delivery ZIP contains symlink: {info.filename}")
            target = destination.joinpath(*member.parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
        if len(roots) != 1:
            raise DeliveryValidationError("delivery ZIP must contain exactly one root directory")
        validate_delivery(
            destination / roots.pop(),
            expected_version,
            expected_model_md5,
            expected_target_speaker,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("delivery_path", type=Path)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    try:
        validate_delivery_path(args.delivery_path, args.version)
    except (DeliveryValidationError, OSError, UnicodeError, zipfile.BadZipFile) as error:
        parser.error(str(error))
    print(f"[OK] zh-en SDK-only delivery validated: {args.delivery_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
