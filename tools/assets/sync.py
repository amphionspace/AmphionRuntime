#!/usr/bin/env python3
"""Synchronize versioned, Git-external collaboration assets with object storage (Tencent COS / Huawei OBS)."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, replace as dataclass_replace
from pathlib import Path, PurePosixPath
from typing import Iterable, Optional


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_MANIFEST = SCRIPT_DIR / "manifest.json"
DEFAULT_DOWNLOAD_ROOT = Path.home() / ".cache" / "amphion-runtime" / "assets"


class AssetError(RuntimeError):
    pass


SUPPORTED_PROVIDERS = ("tencent-cos", "huawei-obs")


@dataclass(frozen=True)
class Storage:
    """One object store. Positional order is kept for existing callers/tests.

    provider: "tencent-cos"（默认存储，2026-11-16 起）或 "huawei-obs"（历史/受限资产只读保留）。
    OBS 通过 endpoint_env 读端点；COS 用 region（可选 endpoint 固定域名），两者凭据都只走环境变量。
    """
    bucket: str
    endpoint_env: str
    access_key_env: str
    secret_key_env: str
    prefix: str
    provider: str = "huawei-obs"
    region: str = ""
    endpoint: str = ""
    name: str = "default"


@dataclass(frozen=True)
class Bundle:
    name: str
    definition: dict
    storage: Storage
    destination_root: Path
    owned: bool

    @property
    def destination(self) -> Path:
        return safe_join(self.destination_root, str(self.definition["destination"]))

    @property
    def object_key(self) -> str:
        return f"{self.storage.prefix.rstrip('/')}/{self.definition['object']}"


def safe_join(root: Path, relative: str) -> Path:
    if PurePosixPath(relative).is_absolute():
        raise AssetError(f"absolute paths are not allowed in asset manifests: {relative}")
    destination = (root / relative).resolve()
    try:
        destination.relative_to(root.resolve())
    except ValueError as error:
        raise AssetError(f"asset path escapes its root: {relative}") from error
    return destination


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            block = source.read(block_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


CLIENT_ENCRYPTION = "client-aes256-gcm"
SUPPORTED_ENCRYPTION = (None, "sse-kms", CLIENT_ENCRYPTION)
ASSET_KEY_ENV = "AMPHION_ASSET_KEY_B64"
ENCRYPTED_MAGIC = b"AMPHENC1"
ENCRYPTED_NONCE_SIZE = 12
ENCRYPTED_SUFFIX = ".zip.enc"


def is_restricted(definition: dict) -> bool:
    return definition.get("encryption") in ("sse-kms", CLIENT_ENCRYPTION)


def is_client_encrypted(definition: dict) -> bool:
    return definition.get("encryption") == CLIENT_ENCRYPTION


def asset_key() -> bytes:
    """客户端加密密钥：环境变量 AMPHION_ASSET_KEY_B64（32 字节 AES-256 密钥的 base64），由团队凭据注入脚本提供。"""
    import base64

    raw = os.environ.get(ASSET_KEY_ENV, "").strip()
    if not raw:
        raise AssetError(
            f"missing {ASSET_KEY_ENV}: client-encrypted bundles need the team asset key "
            "(see tools/assets/README.md, section 受限 bundle)"
        )
    try:
        key = base64.b64decode(raw, validate=True)
    except (ValueError, TypeError) as error:
        raise AssetError(f"{ASSET_KEY_ENV} is not valid base64") from error
    if len(key) != 32:
        raise AssetError(f"{ASSET_KEY_ENV} must decode to 32 bytes, got {len(key)}")
    return key


def aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as error:
        raise AssetError(
            "missing cryptography package for client-encrypted bundles; run with the repository "
            ".venv (python3 -m pip install cryptography)"
        ) from error
    return AESGCM


def encrypted_nonce(key: bytes, plain_sha256: str) -> bytes:
    """确定性 nonce：由密钥与明文 SHA-256 派生。同一明文得到同一密文，便于清单登记与远端比对；
    不同明文的 nonce 不同，满足 AES-GCM 的 nonce 唯一性要求。"""
    import hmac

    return hmac.new(key, b"amphion-asset-nonce:" + plain_sha256.encode("ascii"), hashlib.sha256).digest()[:ENCRYPTED_NONCE_SIZE]


def encrypted_aad(nonce: bytes, plain_sha256: str) -> bytes:
    return ENCRYPTED_MAGIC + nonce + plain_sha256.encode("ascii")


def encrypt_archive(plain: Path, encrypted: Path, plain_sha256: str) -> None:
    key = asset_key()
    nonce = encrypted_nonce(key, plain_sha256)
    data = plain.read_bytes()
    body = aesgcm()(key).encrypt(nonce, data, encrypted_aad(nonce, plain_sha256))
    encrypted.parent.mkdir(parents=True, exist_ok=True)
    encrypted.write_bytes(ENCRYPTED_MAGIC + nonce + body)
    os.chmod(encrypted, 0o600)


def decrypt_archive(encrypted: Path, plain: Path, plain_sha256: str) -> None:
    key = asset_key()
    blob = encrypted.read_bytes()
    header = len(ENCRYPTED_MAGIC) + ENCRYPTED_NONCE_SIZE
    if len(blob) <= header or not blob.startswith(ENCRYPTED_MAGIC):
        raise AssetError(f"{encrypted.name} is not an AMPHENC1 client-encrypted archive")
    nonce = blob[len(ENCRYPTED_MAGIC):header]
    if nonce != encrypted_nonce(key, plain_sha256):
        raise AssetError(f"{encrypted.name} nonce does not match the manifest identity (wrong key or tampered archive)")
    try:
        data = aesgcm()(key).decrypt(nonce, blob[header:], encrypted_aad(nonce, plain_sha256))
    except Exception as error:  # InvalidTag
        raise AssetError(f"{encrypted.name} failed authentication (wrong key or tampered archive)") from error
    plain.write_bytes(data)
    os.chmod(plain, 0o600)


def is_sealed(definition: dict) -> bool:
    """客户端加密包是否已登记密文身份；未登记的条目可以加载，但发布 / 拉取 / 远端校验前必须先 `seal`。"""
    return "encrypted_size" in definition or "encrypted_sha256" in definition


def remote_expectation(definition: dict) -> tuple[int, str, Optional[str]]:
    """远端对象应有的 (size, sha256 元数据, 加密标记)：客户端加密包登记的是密文身份，并要求 COS 侧再叠一层 SSE-COS。"""
    if is_client_encrypted(definition):
        if not is_sealed(definition):
            raise AssetError("client-encrypted bundle has no encrypted identity yet; run: sync.py seal <bundle>")
        return int(definition["encrypted_size"]), str(definition["encrypted_sha256"]), "AES256"
    if definition.get("encryption") == "sse-kms":
        return int(definition["size"]), str(definition["sha256"]), "kms"
    return int(definition["size"]), str(definition["sha256"]), None


def read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AssetError(f"cannot read asset manifest {path}: {error}") from error
    if payload.get("schema_version") != 1:
        raise AssetError(f"unsupported asset manifest schema in {path}")
    return payload


def storage_from(payload: dict, name: str = "default") -> Storage:
    settings = payload if name != "default" else (payload.get("storage") or payload.get("obs"))
    if not isinstance(settings, dict):
        raise AssetError("asset manifest storage must be an object")
    provider = str(settings.get("provider", "huawei-obs"))
    if provider not in SUPPORTED_PROVIDERS:
        raise AssetError(f"storage {name} has unsupported provider {provider}")
    if provider == "huawei-obs" and "endpoint_env" not in settings:
        raise AssetError(f"storage {name} (huawei-obs) needs endpoint_env")
    if provider == "tencent-cos" and not settings.get("region"):
        raise AssetError(f"storage {name} (tencent-cos) needs region")
    return Storage(
        bucket=str(settings["bucket"]),
        endpoint_env=str(settings.get("endpoint_env", "")),
        access_key_env=str(settings["access_key_env"]),
        secret_key_env=str(settings["secret_key_env"]),
        prefix=str(settings["prefix"]),
        provider=provider,
        region=str(settings.get("region", "")),
        endpoint=str(settings.get("endpoint", "")).rstrip("/"),
        name=name,
    )


def storages_from(payload: dict) -> dict[str, Storage]:
    """默认 storage 加上 `storages` 里的具名存储（例如只读保留的 obs-legacy）。"""
    storages = {"default": storage_from(payload)}
    extra = payload.get("storages", {})
    if not isinstance(extra, dict):
        raise AssetError("asset manifest storages must be an object")
    for name, settings in extra.items():
        if name == "default":
            raise AssetError("storages must not redefine default")
        storages[name] = storage_from(settings, name)
    return storages


def test_data_root(payload: dict) -> Path:
    configured = os.environ.get("AMPHION_TEST_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (
        Path.home()
        / ".cache"
        / "amphion-runtime"
        / "test-data"
        / str(payload["dataset_version"])
    ).resolve()


def validate_bundle(name: str, definition: dict) -> None:
    if definition.get("status", "current") not in ("current", "historical"):
        raise AssetError(f"bundle {name} has an invalid status")
    required = (
        "description",
        "license",
        "redistribution",
        "destination",
        "archive_root",
        "archive_type",
        "object",
        "size",
        "sha256",
    )
    missing = [key for key in required if key not in definition]
    if missing:
        raise AssetError(f"bundle {name} is missing: {', '.join(missing)}")
    if definition["archive_type"] != "zip":
        raise AssetError(f"bundle {name} uses unsupported archive type")
    if len(str(definition["sha256"])) != 64 or int(definition["size"]) <= 0:
        raise AssetError(f"bundle {name} has an invalid archive identity")
    if definition.get("encryption") not in SUPPORTED_ENCRYPTION:
        raise AssetError(f"bundle {name} has an unsupported encryption mode {definition.get('encryption')!r}")
    if is_client_encrypted(definition) and is_sealed(definition):
        if not str(definition["object"]).endswith(ENCRYPTED_SUFFIX):
            raise AssetError(f"bundle {name} client-encrypted object must end with {ENCRYPTED_SUFFIX}")
        if (
            len(str(definition.get("encrypted_sha256", ""))) != 64
            or int(definition.get("encrypted_size", 0)) <= int(definition["size"])
        ):
            raise AssetError(f"bundle {name} has an invalid encrypted archive identity")


def load_registry(manifest_path: Path, repo_root: Path) -> tuple[dict, dict[str, Bundle]]:
    manifest = read_json(manifest_path)
    storages = storages_from(manifest)
    raw_bundles = manifest.get("bundles")
    if not isinstance(raw_bundles, dict):
        raise AssetError("asset manifest bundles must be an object")
    bundles: dict[str, Bundle] = {}
    for name, definition in raw_bundles.items():
        validate_bundle(name, definition)
        storage_name = str(definition.get("storage", "default"))
        if storage_name not in storages:
            raise AssetError(f"bundle {name} references unknown storage {storage_name}")
        bundles[name] = Bundle(name, definition, storages[storage_name], repo_root, True)

    for include in manifest.get("included_manifests", []):
        include_path = safe_join(repo_root, str(include["path"]))
        included = read_json(include_path)
        if include.get("kind") != "test-data":
            raise AssetError(f"unsupported included manifest kind: {include.get('kind')}")
        included_storage = dataclass_replace(storage_from(included), name="test-data")
        root = test_data_root(included)
        for name, definition in included.get("bundles", {}).items():
            if name in bundles:
                raise AssetError(f"duplicate asset bundle name: {name}")
            validate_bundle(name, definition)
            normalized = dict(definition)
            normalized["destination"] = str(definition["destination"])
            bundles[name] = Bundle(name, normalized, included_storage, root, False)
    return manifest, bundles


def selected_bundles(bundles: dict[str, Bundle], requested: Iterable[str]) -> list[Bundle]:
    names = list(requested)
    lookup = {name: name for name in bundles}
    for name, bundle in bundles.items():
        for alias in bundle.definition.get("aliases", []):
            if alias in lookup or alias == "all":
                raise AssetError(f"duplicate or reserved asset alias: {alias}")
            lookup[alias] = name
    if names == ["all"]:
        return [
            bundles[name] for name in sorted(bundles)
            if bundles[name].definition.get("status", "current") == "current"
        ]
    unknown = sorted(set(names) - set(lookup))
    if unknown:
        raise AssetError(f"unknown asset bundle(s): {', '.join(unknown)}")
    return [bundles[name] for name in dict.fromkeys(lookup[name] for name in names)]


def expected_files(bundle: Bundle) -> dict[str, dict]:
    files = bundle.definition.get("files", [])
    return {str(item["path"]): item for item in files}


def verify_file_identities(
    destination: Path, bundle: Bundle, *, allow_extra: bool, check_mode: bool = True
) -> None:
    files = expected_files(bundle)
    if files:
        actual = {
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*")
            if path.is_file() and path.name != ".DS_Store"
        }
        expected = set(files)
        missing = sorted(expected - actual)
        extra = [] if allow_extra else sorted(actual - expected)
        if missing or extra:
            details = []
            if missing:
                details.append(f"missing={','.join(missing)}")
            if extra:
                details.append(f"unexpected={','.join(extra)}")
            raise AssetError(f"bundle {bundle.name} file set mismatch: {'; '.join(details)}")
        for relative, identity in files.items():
            path = safe_join(destination, relative)
            actual_size = path.stat().st_size
            if actual_size != int(identity["size"]):
                raise AssetError(
                    f"bundle {bundle.name} size mismatch for {relative}: "
                    f"expected {identity['size']}, got {actual_size}"
                )
            actual_hash = sha256_file(path)
            if actual_hash != identity["sha256"]:
                raise AssetError(
                    f"bundle {bundle.name} SHA-256 mismatch for {relative}: "
                    f"expected {identity['sha256']}, got {actual_hash}"
                )
            if check_mode and "mode" in identity:
                expected_mode = int(str(identity["mode"]), 8)
                actual_mode = stat.S_IMODE(path.stat().st_mode)
                if actual_mode != expected_mode:
                    raise AssetError(
                        f"bundle {bundle.name} mode mismatch for {relative}: "
                        f"expected {expected_mode:04o}, got {actual_mode:04o}"
                    )


def verify_local(bundle: Bundle) -> Path:
    destination = bundle.destination
    if not destination.is_dir():
        raise AssetError(f"bundle {bundle.name} is missing: {destination}")
    if is_restricted(bundle.definition):
        directory_mode = stat.S_IMODE(destination.stat().st_mode)
        if directory_mode & 0o077:
            raise AssetError(
                f"restricted bundle directory is too permissive: "
                f"{destination} mode={directory_mode:04o}; expected 0700"
            )
    files = expected_files(bundle)
    if files:
        verify_file_identities(
            destination,
            bundle,
            allow_extra=bool(bundle.definition.get("allow_extra_files")),
        )
    else:
        missing = [
            item
            for item in bundle.definition.get("required_paths", [])
            if not safe_join(destination, str(item)).exists()
        ]
        if missing:
            raise AssetError(f"bundle {bundle.name} is incomplete: {', '.join(missing)}")
    return destination


def verify_archive(path: Path, bundle: Bundle) -> None:
    actual_size = path.stat().st_size
    if actual_size != int(bundle.definition["size"]):
        raise AssetError(
            f"archive size mismatch for {bundle.name}: "
            f"expected {bundle.definition['size']}, got {actual_size}"
        )
    actual_hash = sha256_file(path)
    if actual_hash != bundle.definition["sha256"]:
        raise AssetError(
            f"archive SHA-256 mismatch for {bundle.name}: "
            f"expected {bundle.definition['sha256']}, got {actual_hash}"
        )


def build_archive(bundle: Bundle, archive: Path) -> None:
    if not bundle.owned or not expected_files(bundle):
        raise AssetError(f"bundle {bundle.name} is not built from repository assets")
    verify_local(bundle)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as payload:
        for relative in sorted(expected_files(bundle)):
            source = safe_join(bundle.destination, relative)
            archive_name = f"{bundle.definition['archive_root']}/{relative}"
            info = zipfile.ZipInfo(archive_name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            identity = expected_files(bundle)[relative]
            mode = int(str(identity.get("mode", "0644")), 8)
            info.external_attr = (stat.S_IFREG | mode) << 16
            payload.writestr(
                info,
                source.read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
    verify_archive(archive, bundle)


def safe_extract(archive: Path, stage: Path, bundle: Bundle) -> Path:
    with zipfile.ZipFile(archive) as payload:
        for item in payload.infolist():
            safe_join(stage, item.filename)
            file_type = (item.external_attr >> 16) & 0o170000
            if file_type == stat.S_IFLNK:
                raise AssetError(f"archive links are not allowed: {item.filename}")
        payload.extractall(stage)
        for item in payload.infolist():
            if item.is_dir():
                continue
            mode = stat.S_IMODE(item.external_attr >> 16)
            if mode:
                os.chmod(safe_join(stage, item.filename), mode)
    extracted = safe_join(stage, str(bundle.definition["archive_root"]))
    if not extracted.is_dir():
        raise AssetError(
            f"archive for {bundle.name} is missing root {bundle.definition['archive_root']}"
        )
    return extracted


def replace_destination(extracted: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    ready = destination.parent / f".{destination.name}.ready-{uuid.uuid4().hex}"
    backup = destination.parent / f".{destination.name}.backup-{uuid.uuid4().hex}"
    extracted.rename(ready)
    try:
        if destination.exists():
            destination.rename(backup)
        ready.rename(destination)
    except BaseException:
        if not destination.exists() and backup.exists():
            backup.rename(destination)
        raise
    finally:
        if ready.exists():
            shutil.rmtree(ready)
        if backup.exists():
            shutil.rmtree(backup)


def merge_destination(
    extracted: Path, bundle: Bundle, *, replace_existing: bool = False
) -> None:
    verify_file_identities(extracted, bundle, allow_extra=False, check_mode=False)
    destination = bundle.destination
    destination.mkdir(parents=True, exist_ok=True)
    if is_restricted(bundle.definition):
        os.chmod(destination, 0o700)

    conflicts = []
    for relative, identity in expected_files(bundle).items():
        target = safe_join(destination, relative)
        if not target.exists():
            continue
        same = (
            target.is_file()
            and target.stat().st_size == int(identity["size"])
            and sha256_file(target) == identity["sha256"]
        )
        if not same and not replace_existing:
            conflicts.append(relative)
    if conflicts:
        raise AssetError(
            f"bundle {bundle.name} would replace existing restricted file(s): "
            f"{', '.join(sorted(conflicts))}; re-run fetch with --replace-existing"
        )

    for relative, identity in expected_files(bundle).items():
        source = safe_join(extracted, relative)
        target = safe_join(destination, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        ready = target.parent / f".{target.name}.ready-{uuid.uuid4().hex}"
        try:
            shutil.copyfile(source, ready)
            os.chmod(ready, int(str(identity.get("mode", "0600")), 8))
            os.replace(ready, target)
        finally:
            ready.unlink(missing_ok=True)


def storage_credentials(storage: Storage) -> dict[str, str]:
    pairs = [("access_key", storage.access_key_env), ("secret_key", storage.secret_key_env)]
    if storage.provider == "huawei-obs":
        pairs.insert(0, ("endpoint", storage.endpoint_env))
    values = {}
    for field, env_name in pairs:
        value = os.environ.get(env_name)
        if not value:
            raise AssetError(f"missing {storage.provider} environment variable: {env_name}")
        values[field] = value
    return values


def obs_client(storage: Storage):
    values = storage_credentials(storage)
    try:
        from obs import ObsClient
    except ImportError as error:
        raise AssetError(
            "missing Huawei OBS SDK; run: python3 -m pip install esdk-obs-python"
        ) from error
    return ObsClient(
        access_key_id=values["access_key"],
        secret_access_key=values["secret_key"],
        server=values["endpoint"],
    )


def cos_client(storage: Storage):
    values = storage_credentials(storage)
    try:
        from qcloud_cos import CosConfig, CosS3Client
    except ImportError as error:
        raise AssetError(
            "missing Tencent COS SDK; run: python3 -m pip install cos-python-sdk-v5"
        ) from error
    options = dict(Region=storage.region, SecretId=values["access_key"],
                   SecretKey=values["secret_key"], Scheme="https")
    if storage.endpoint:
        options["Endpoint"] = storage.endpoint.split("://", 1)[-1]
    return CosS3Client(CosConfig(**options))


class CosNotFound(Exception):
    pass


def cos_head(client, storage: Storage, key: str) -> dict[str, str]:
    from qcloud_cos.cos_exception import CosServiceError
    try:
        headers = client.head_object(Bucket=storage.bucket, Key=key)
    except CosServiceError as error:
        if error.get_status_code() == 404:
            raise CosNotFound(key) from error
        raise AssetError(
            f"cannot inspect tencent-cos object {key}: status={error.get_status_code()} "
            f"code={error.get_error_code()}"
        ) from error
    return {str(k).lower(): str(v) for k, v in headers.items()}


def cos_identity_from_headers(headers: dict[str, str]) -> tuple[int, Optional[str], Optional[str]]:
    """COS 响应头 → (size, sha256 元数据, 加密标记)。`cos/kms` 归一为 \"kms\"，与 OBS 的判定口径一致。"""
    content_length = headers.get("content-length")
    if content_length is None:
        raise AssetError("tencent-cos object has no content-length")
    sse = headers.get("x-cos-server-side-encryption", "")
    encryption = "kms" if sse.lower().startswith("cos/kms") else (sse or None)
    return int(content_length), headers.get("x-cos-meta-sha256"), encryption


def response_header(response, name: str) -> Optional[str]:
    wanted = name.lower()
    for key, value in response.header or []:
        if str(key).lower() == wanted:
            return str(value)
    return None


def remote_identity_or_none(bundle: Bundle) -> Optional[tuple[int, Optional[str], Optional[str]]]:
    """远端对象的 (size, sha256 元数据, 加密标记)；对象不存在时返回 None。"""
    storage = bundle.storage
    if storage.provider == "tencent-cos":
        client = cos_client(storage)
        try:
            headers = cos_head(client, storage, bundle.object_key)
        except CosNotFound:
            return None
        return cos_identity_from_headers(headers)
    client = obs_client(storage)
    try:
        response = client.getObjectMetadata(storage.bucket, bundle.object_key)
    finally:
        client.close()
    if response.status == 404:
        return None
    if response.status >= 300:
        raise AssetError(
            f"cannot inspect huawei-obs object for {bundle.name}: "
            f"status={response.status} code={response.errorCode}"
        )
    content_length = response_header(response, "content-length")
    if content_length is None:
        raise AssetError(f"huawei-obs object has no content-length: {bundle.object_key}")
    metadata_hash = response_header(response, "x-obs-meta-sha256")
    encryption = getattr(response.body, "sseKms", None)
    return int(content_length), metadata_hash, encryption


def remote_identity(bundle: Bundle) -> tuple[int, Optional[str], Optional[str]]:
    identity = remote_identity_or_none(bundle)
    if identity is None:
        raise AssetError(
            f"cannot inspect {bundle.storage.provider} object for {bundle.name}: status=404 "
            f"({bundle.storage.bucket}/{bundle.object_key})"
        )
    return identity


def download_archive(bundle: Bundle, archive: Path, checkpoint: Path, *, restricted: bool) -> None:
    storage = bundle.storage
    if storage.provider == "tencent-cos":
        client = cos_client(storage)
        client.download_file(
            Bucket=storage.bucket, Key=bundle.object_key, DestFilePath=str(archive),
            PartSize=20, MAXThread=4, EnableCRC=False,
            DumpRecordDir=None if restricted else str(archive.parent),
        )
        return
    client = obs_client(storage)
    try:
        response = client.downloadFile(
            storage.bucket,
            bundle.object_key,
            str(archive),
            partSize=20 * 1024 * 1024,
            taskNum=4,
            enableCheckpoint=not restricted,
            checkpointFile=None if restricted else str(checkpoint),
        )
    finally:
        client.close()
    if response.status >= 300:
        raise AssetError(
            f"huawei-obs download failed for {bundle.name}: "
            f"status={response.status} code={response.errorCode}"
        )


def upload_archive(bundle: Bundle, archive: Path, checkpoint: Path, *, restricted: bool) -> None:
    storage = bundle.storage
    _, sha256, required_encryption = remote_expectation(bundle.definition)
    if storage.provider == "tencent-cos":
        client = cos_client(storage)
        options = {"Metadata": {"x-cos-meta-sha256": sha256}}
        if required_encryption == "kms":
            options["ServerSideEncryption"] = "cos/kms"
        elif required_encryption == "AES256":
            options["ServerSideEncryption"] = "AES256"
        client.upload_file(
            Bucket=storage.bucket, Key=bundle.object_key, LocalFilePath=str(archive),
            PartSize=20, MAXThread=4, EnableMD5=True, **options,
        )
        return
    headers = None
    if restricted:
        try:
            from obs import PutObjectHeader, SseKmsHeader
        except ImportError as error:
            raise AssetError(
                "missing Huawei OBS SDK; run: python3 -m pip install esdk-obs-python"
            ) from error
        headers = PutObjectHeader(sseHeader=SseKmsHeader.getInstance())
    client = obs_client(storage)
    try:
        response = client.uploadFile(
            storage.bucket,
            bundle.object_key,
            str(archive),
            partSize=20 * 1024 * 1024,
            taskNum=4,
            enableCheckpoint=not restricted,
            checkpointFile=None if restricted else str(checkpoint),
            metadata={"sha256": sha256},
            headers=headers,
        )
    finally:
        client.close()
    if response.status >= 300:
        raise AssetError(
            f"huawei-obs upload failed for {bundle.name}: "
            f"status={response.status} code={response.errorCode}"
        )


def verify_remote(bundle: Bundle) -> None:
    size, metadata_hash, encryption = remote_identity(bundle)
    expected_size, expected_hash, required_encryption = remote_expectation(bundle.definition)
    if size != expected_size:
        raise AssetError(
            f"remote size mismatch for {bundle.name}: expected {expected_size}, got {size}"
        )
    if metadata_hash and metadata_hash != expected_hash:
        raise AssetError(
            f"remote SHA-256 metadata mismatch for {bundle.name}: "
            f"expected {expected_hash}, got {metadata_hash}"
        )
    if required_encryption == "kms" and encryption != "kms":
        raise AssetError(f"remote object for {bundle.name} is not encrypted with SSE-KMS")
    if required_encryption == "AES256" and (encryption or "").upper() != "AES256":
        raise AssetError(f"remote object for {bundle.name} lacks the SSE-COS AES256 layer")


def download_root() -> Path:
    configured = os.environ.get("AMPHION_ASSET_CACHE_DIR")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_DOWNLOAD_ROOT


def fetch_bundle(bundle: Bundle, *, replace_existing: bool = False) -> Path:
    try:
        return verify_local(bundle)
    except AssetError:
        pass
    restricted = is_restricted(bundle.definition)
    client_encrypted = is_client_encrypted(bundle.definition)
    downloads = download_root() / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    if restricted:
        os.chmod(downloads, 0o700)
    archive = downloads / f"{bundle.name}-{bundle.definition['sha256']}.zip"
    encrypted = archive.with_suffix(ENCRYPTED_SUFFIX)
    checkpoint = archive.with_suffix(".zip.checkpoint")
    try:
        if client_encrypted:
            if not archive.exists():
                download_archive(bundle, encrypted, checkpoint, restricted=True)
                verify_encrypted_archive(encrypted, bundle)
                decrypt_archive(encrypted, archive, str(bundle.definition["sha256"]))
        elif not archive.exists():
            download_archive(bundle, archive, checkpoint, restricted=restricted)
        if restricted:
            os.chmod(archive, 0o600)
        verify_archive(archive, bundle)
        bundle.destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            dir=bundle.destination.parent, prefix=f".{bundle.destination.name}.extract-"
        ) as temporary:
            extracted = safe_extract(archive, Path(temporary), bundle)
            if bundle.definition.get("merge_destination"):
                merge_destination(extracted, bundle, replace_existing=replace_existing)
            else:
                replace_destination(extracted, bundle.destination)
        verify_local(bundle)
        archive.unlink()
        checkpoint.unlink(missing_ok=True)
        return bundle.destination
    finally:
        if restricted:
            archive.unlink(missing_ok=True)
            encrypted.unlink(missing_ok=True)
            checkpoint.unlink(missing_ok=True)


def verify_encrypted_archive(path: Path, bundle: Bundle) -> None:
    expected_size, expected_hash, _ = remote_expectation(bundle.definition)
    actual_size = path.stat().st_size
    if actual_size != expected_size:
        raise AssetError(
            f"encrypted archive size mismatch for {bundle.name}: expected {expected_size}, got {actual_size}"
        )
    actual_hash = sha256_file(path)
    if actual_hash != expected_hash:
        raise AssetError(
            f"encrypted archive SHA-256 mismatch for {bundle.name}: expected {expected_hash}, got {actual_hash}"
        )


def assert_remote_matches_or_absent(bundle: Bundle) -> bool:
    """远端已有同键对象时必须与清单身份一致（不覆盖不同内容）；返回是否已存在。"""
    existing = remote_identity_or_none(bundle)
    if existing is None:
        return False
    size, metadata_hash, encryption = existing
    expected_size, expected_hash, required_encryption = remote_expectation(bundle.definition)
    if size != expected_size:
        raise AssetError(
            f"refusing to replace {bundle.storage.provider} object with different size: {bundle.object_key}"
        )
    if metadata_hash and metadata_hash != expected_hash:
        raise AssetError(
            f"refusing to replace {bundle.storage.provider} object with different SHA-256: {bundle.object_key}"
        )
    if required_encryption == "kms" and encryption != "kms":
        raise AssetError(f"refusing unencrypted existing restricted object: {bundle.object_key}")
    if required_encryption == "AES256" and (encryption or "").upper() != "AES256":
        raise AssetError(f"refusing existing restricted object without SSE-COS layer: {bundle.object_key}")
    return True


def publish_bundle(bundle: Bundle) -> str:
    if not bundle.owned:
        raise AssetError(f"included bundle {bundle.name} is published by its owning tool")
    restricted = is_restricted(bundle.definition)
    client_encrypted = is_client_encrypted(bundle.definition)
    uploads = download_root() / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    if restricted:
        os.chmod(uploads, 0o700)
    archive = uploads / f"{bundle.name}-{bundle.definition['sha256']}.zip"
    encrypted = archive.with_suffix(ENCRYPTED_SUFFIX)
    checkpoint = archive.with_suffix(".zip.upload-checkpoint")
    try:
        build_archive(bundle, archive)
        if restricted:
            os.chmod(archive, 0o600)
        upload_path = archive
        if client_encrypted:
            encrypt_archive(archive, encrypted, str(bundle.definition["sha256"]))
            try:
                verify_encrypted_archive(encrypted, bundle)
            except AssetError as error:
                raise AssetError(
                    f"{error}; the manifest encrypted identity is stale or the key differs — "
                    f"run: sync.py seal {bundle.name}"
                ) from error
            upload_path = encrypted
        if assert_remote_matches_or_absent(bundle):
            archive.unlink()
            return "already-present"
        upload_archive(bundle, upload_path, checkpoint, restricted=restricted)
        verify_remote(bundle)
        archive.unlink()
        checkpoint.unlink(missing_ok=True)
        return "uploaded"
    finally:
        if restricted:
            archive.unlink(missing_ok=True)
            encrypted.unlink(missing_ok=True)
            checkpoint.unlink(missing_ok=True)


def seal_bundle(bundle: Bundle, manifest_path: Path) -> dict:
    """为客户端加密的 bundle 计算并写回密文身份（object / encrypted_size / encrypted_sha256）。

    归档由本地文件按清单确定性构造，再用团队密钥确定性加密，因此同一内容总得到同一密文身份。
    """
    if not is_client_encrypted(bundle.definition):
        raise AssetError(f"bundle {bundle.name} is not {CLIENT_ENCRYPTION}; nothing to seal")
    uploads = download_root() / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    os.chmod(uploads, 0o700)
    archive = uploads / f"{bundle.name}-{bundle.definition['sha256']}.zip"
    encrypted = archive.with_suffix(ENCRYPTED_SUFFIX)
    try:
        build_archive(bundle, archive)
        os.chmod(archive, 0o600)
        encrypt_archive(archive, encrypted, str(bundle.definition["sha256"]))
        current_object = str(bundle.definition["object"])
        prefix = current_object.rsplit("/", 1)[0] if "/" in current_object else bundle.name
        identity = {
            "object": f"{prefix}/{bundle.definition['sha256']}{ENCRYPTED_SUFFIX}",
            "encrypted_size": encrypted.stat().st_size,
            "encrypted_sha256": sha256_file(encrypted),
        }
    finally:
        archive.unlink(missing_ok=True)
        encrypted.unlink(missing_ok=True)
    payload = read_json(manifest_path)
    entry = payload["bundles"][bundle.name]
    changed = {k: v for k, v in identity.items() if entry.get(k) != v}
    entry.update(identity)
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    bundle.definition.update(identity)
    return changed


def mirror_bundle(bundle: Bundle, source: Storage) -> str:
    """把 bundle 的归档从 source 存储原样搬到清单声明的目标存储（不需要本地解压文件）。

    下载后先按清单校验整包 SHA-256，再上传并做远端校验；目标已有同身份对象时跳过。
    受限（SSE-KMS）bundle 不走镜像：目标侧的 KMS 密钥另行决定，它们保留在原存储。
    """
    if is_restricted(bundle.definition):
        raise AssetError(f"restricted bundle {bundle.name} is not mirrored; publish it from local files instead")
    if source == bundle.storage:
        return "same-storage"
    if assert_remote_matches_or_absent(bundle):
        return "already-present"
    staging = download_root() / "mirror"
    staging.mkdir(parents=True, exist_ok=True)
    archive = staging / f"{bundle.name}-{bundle.definition['sha256']}.zip"
    checkpoint = archive.with_suffix(".zip.checkpoint")
    origin = Bundle(bundle.name, bundle.definition, source, bundle.destination_root, bundle.owned)
    if not archive.exists():
        download_archive(origin, archive, checkpoint, restricted=False)
    verify_archive(archive, bundle)
    upload_archive(bundle, archive, archive.with_suffix(".zip.upload-checkpoint"), restricted=False)
    verify_remote(bundle)
    archive.unlink()
    checkpoint.unlink(missing_ok=True)
    return "mirrored"


def ignored_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--others", "--ignored", "--exclude-standard"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def policy_match(path: str, manifest: dict) -> Optional[str]:
    for exclusion in manifest.get("ignored_asset_policy", {}).get("excluded", []):
        for pattern in exclusion.get("patterns", []):
            if fnmatch.fnmatch(path, pattern):
                return str(exclusion["category"])
    return None


def audit_ignored(repo_root: Path, manifest: dict, bundles: dict[str, Bundle]) -> dict[str, int]:
    managed: dict[str, tuple[set[str], bool]] = {}
    for bundle in bundles.values():
        if not bundle.owned:
            continue
        root = bundle.destination.relative_to(repo_root.resolve()).as_posix().rstrip("/")
        expected = {f"{root}/{path}" for path in expected_files(bundle)}
        existing, allow_extra = managed.get(root, (set(), False))
        managed[root] = (
            existing | expected,
            allow_extra or bool(bundle.definition.get("allow_extra_files")),
        )

    counts: dict[str, int] = {}
    violations = []
    for path in ignored_files(repo_root):
        handled = False
        for root, (expected, allow_extra) in managed.items():
            if path == root or path.startswith(root + "/"):
                if path in expected:
                    counts["synchronized"] = counts.get("synchronized", 0) + 1
                    handled = True
                elif not allow_extra:
                    violations.append(f"unlisted file under synchronized asset root: {path}")
                    handled = True
                break
        if handled:
            continue
        category = policy_match(path, manifest)
        if category:
            counts[category] = counts.get(category, 0) + 1
        else:
            violations.append(f"unclassified Git-ignored file: {path}")
    if violations:
        preview = "\n".join(violations[:50])
        suffix = "" if len(violations) <= 50 else f"\n... and {len(violations) - 50} more"
        raise AssetError(f"asset audit found {len(violations)} violation(s):\n{preview}{suffix}")
    return counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    commands.add_parser("audit")
    fetch = commands.add_parser("fetch")
    fetch.add_argument("bundles", nargs="+", help="bundle names/aliases, or 'all' for current bundles")
    fetch.add_argument(
        "--replace-existing",
        action="store_true",
        help="replace conflicting files in merge-style restricted bundles",
    )
    for command in ("verify", "remote-verify", "publish"):
        child = commands.add_parser(command)
        child.add_argument("bundles", nargs="+", help="bundle names/aliases, or 'all' for current bundles")
    seal = commands.add_parser("seal", help="compute and record the encrypted identity of client-encrypted bundles")
    seal.add_argument("bundles", nargs="+", help="client-encrypted bundle names")
    mirror = commands.add_parser("mirror", help="copy archives from a named legacy storage to the manifest storage")
    mirror.add_argument("--from", dest="source", required=True, help="source storage name from manifest.storages")
    mirror.add_argument("bundles", nargs="+", help="bundle names/aliases, or 'all' for current bundles")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.expanduser().resolve()
    manifest_path = args.manifest.expanduser().resolve()
    try:
        manifest, bundles = load_registry(manifest_path, repo_root)
        if args.command == "list":
            for name, bundle in sorted(bundles.items()):
                scope = "repository" if bundle.owned else "test-data-cache"
                aliases = ",".join(bundle.definition.get("aliases", [])) or "-"
                print(
                    f"{name}\t{bundle.definition.get('status', 'current')}\t{scope}\t"
                    f"{bundle.definition['size']}\t{bundle.definition['license']}\t"
                    f"{bundle.definition['description']}\taliases={aliases}\t"
                    f"storage={bundle.storage.name}:{bundle.storage.provider}"
                )
            for include in manifest.get("included_manifests", []):
                included = read_json(safe_join(repo_root, str(include["path"])))
                for name, entry in sorted(included.get("catalog", {}).items()):
                    scheme = "cos" if entry.get("provider") == "tencent-cos" else "obs"
                    print(
                        f"{name}\tcatalog-only\t{scheme}://{entry['bucket']}/{entry['object_key']}\t"
                        f"{entry['size']}\t{entry['description']}\tmanual download; see asr/test-data/README.md"
                    )
            return 0
        if args.command == "audit":
            counts = audit_ignored(repo_root, manifest, bundles)
            summary = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
            print(f"asset audit: PASS ({summary or 'no ignored files'})")
            return 0
        chosen = selected_bundles(bundles, args.bundles)
        if args.command == "verify":
            for bundle in chosen:
                print(f"verified {bundle.name}: {verify_local(bundle)}")
        elif args.command == "fetch":
            for bundle in chosen:
                print(
                    f"fetched {bundle.name}: "
                    f"{fetch_bundle(bundle, replace_existing=args.replace_existing)}"
                )
        elif args.command == "remote-verify":
            for bundle in chosen:
                verify_remote(bundle)
                print(f"remote verified {bundle.name}")
        elif args.command == "publish":
            for bundle in chosen:
                print(f"{publish_bundle(bundle)} {bundle.name}")
        elif args.command == "seal":
            for bundle in chosen:
                changed = seal_bundle(bundle, manifest_path)
                print(f"sealed {bundle.name}: {'updated ' + ', '.join(sorted(changed)) if changed else 'unchanged'}")
        elif args.command == "mirror":
            storages = storages_from(manifest)
            if args.source not in storages:
                raise AssetError(f"unknown source storage {args.source}; known: {', '.join(sorted(storages))}")
            for bundle in chosen:
                if not bundle.owned:
                    print(f"skipped {bundle.name}: included test-data bundle stays on its own storage")
                    continue
                print(f"{mirror_bundle(bundle, storages[args.source])} {bundle.name}")
        return 0
    except (AssetError, OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
