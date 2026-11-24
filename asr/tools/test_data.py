#!/usr/bin/env python3
"""Fetch, verify, and publish versioned test-data bundles stored in object storage (Tencent COS by default; Huawei OBS manifests still supported)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
MANIFEST_PATH = REPO_ROOT / "asr" / "test-data" / "manifest.json"
DEFAULT_CACHE_PARENT = Path.home() / ".cache" / "amphion-runtime" / "test-data"


class TestDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class StorageConfig:
    provider: str
    bucket: str
    prefix: str
    access_key: str
    secret_key: str
    endpoint: str = ""
    region: str = ""


# 兼容旧名称：历史脚本/测试引用过 ObsConfig。
ObsConfig = StorageConfig


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TestDataError(f"cannot read test-data manifest {path}: {error}") from error
    if manifest.get("schema_version") != 1:
        raise TestDataError("unsupported test-data manifest schema")
    if not isinstance(manifest.get("bundles"), dict):
        raise TestDataError("test-data manifest bundles must be an object")
    for name, bundle in manifest["bundles"].items():
        if bundle.get("status", "current") not in ("current", "historical"):
            raise TestDataError(f"bundle {name} has an invalid status")
    return manifest


def cache_root(manifest: dict) -> Path:
    configured = os.environ.get("AMPHION_TEST_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (DEFAULT_CACHE_PARENT / str(manifest["dataset_version"])).resolve()


def bundle_dir(manifest: dict, name: str) -> Path:
    bundle = manifest["bundles"][name]
    return cache_root(manifest) / str(bundle["destination"])


def selected_bundle_names(manifest: dict, requested: Iterable[str]) -> list[str]:
    names = list(requested)
    bundles = manifest["bundles"]
    lookup = {name: name for name in bundles}
    for name, bundle in bundles.items():
        for alias in bundle.get("aliases", []):
            if alias in lookup or alias == "all":
                raise TestDataError(f"duplicate or reserved test-data alias: {alias}")
            lookup[alias] = name
    if names == ["all"]:
        return sorted(name for name, bundle in bundles.items() if bundle.get("status", "current") == "current")
    unknown = sorted(set(names) - set(lookup))
    if unknown:
        raise TestDataError(f"unknown test-data bundle(s): {', '.join(unknown)}")
    return list(dict.fromkeys(lookup[name] for name in names))


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def verify_archive(path: Path, bundle: dict) -> None:
    expected_size = int(bundle["size"])
    actual_size = path.stat().st_size
    if actual_size != expected_size:
        raise TestDataError(
            f"{path.name} size mismatch: expected {expected_size}, got {actual_size}"
        )
    actual_hash = sha256_file(path)
    if actual_hash != bundle["sha256"]:
        raise TestDataError(
            f"{path.name} SHA-256 mismatch: expected {bundle['sha256']}, got {actual_hash}"
        )


def _safe_member_path(root: Path, name: str) -> Path:
    destination = (root / name).resolve()
    try:
        destination.relative_to(root.resolve())
    except ValueError as error:
        raise TestDataError(f"archive member escapes destination: {name}") from error
    return destination


def extract_archive(archive: Path, destination_parent: Path, bundle: dict) -> None:
    destination_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=destination_parent, prefix=f".{bundle['destination']}.extract-"
    ) as temporary:
        stage = Path(temporary)
        archive_type = bundle["archive_type"]
        if archive_type == "zip":
            with zipfile.ZipFile(archive) as payload:
                for item in payload.infolist():
                    _safe_member_path(stage, item.filename)
                payload.extractall(stage)
        elif archive_type in ("tar", "tar.gz"):
            mode = "r:gz" if archive_type == "tar.gz" else "r:"
            with tarfile.open(archive, mode) as payload:
                for item in payload.getmembers():
                    _safe_member_path(stage, item.name)
                    if item.issym() or item.islnk():
                        raise TestDataError(f"archive links are not allowed: {item.name}")
                payload.extractall(stage)
        else:
            raise TestDataError(f"unsupported archive type: {archive_type}")

        extracted = stage / str(bundle["archive_root"])
        if not extracted.is_dir():
            raise TestDataError(f"archive is missing root directory {bundle['archive_root']}")
        target = destination_parent / str(bundle["destination"])
        replacement = destination_parent / f".{target.name}.ready"
        if replacement.exists():
            shutil.rmtree(replacement)
        extracted.rename(replacement)
        if target.exists():
            shutil.rmtree(target)
        replacement.rename(target)


def storage_settings(manifest: dict) -> dict:
    """默认存储块：新清单用 `storage`（可声明 provider），旧清单用 `obs`。"""
    settings = manifest.get("storage") or manifest.get("obs")
    if not isinstance(settings, dict):
        raise TestDataError("test-data manifest storage must be an object")
    return settings


def storage_config(manifest: dict) -> StorageConfig:
    settings = storage_settings(manifest)
    provider = str(settings.get("provider", "huawei-obs"))
    if provider not in ("huawei-obs", "tencent-cos"):
        raise TestDataError(f"unsupported test-data storage provider: {provider}")
    values = {}
    pairs = [("access_key", settings["access_key_env"]), ("secret_key", settings["secret_key_env"])]
    if provider == "huawei-obs":
        pairs.insert(0, ("endpoint", settings["endpoint_env"]))
    for field, key in pairs:
        value = os.environ.get(key)
        if not value:
            raise TestDataError(f"missing {provider} environment variable: {key}")
        values[field] = value
    if provider == "tencent-cos":
        values["endpoint"] = str(settings.get("endpoint", "")).rstrip("/")
        values["region"] = str(settings.get("region", ""))
        if not values["region"]:
            raise TestDataError("tencent-cos test-data storage needs region")
    return StorageConfig(provider=provider, bucket=str(settings["bucket"]), prefix=str(settings["prefix"]), **values)


obs_config = storage_config  # 兼容旧名称


def obs_client(config: StorageConfig):
    try:
        from obs import ObsClient
    except ImportError as error:
        raise TestDataError(
            "missing Huawei OBS SDK; run: python3 -m pip install esdk-obs-python"
        ) from error
    return ObsClient(
        access_key_id=config.access_key,
        secret_access_key=config.secret_key,
        server=config.endpoint,
    )


def cos_client(config: StorageConfig):
    try:
        from qcloud_cos import CosConfig, CosS3Client
    except ImportError as error:
        raise TestDataError(
            "missing Tencent COS SDK; run: python3 -m pip install cos-python-sdk-v5"
        ) from error
    options = dict(Region=config.region, SecretId=config.access_key, SecretKey=config.secret_key, Scheme="https")
    if config.endpoint:
        options["Endpoint"] = config.endpoint.split("://", 1)[-1]
    return CosS3Client(CosConfig(**options))


def object_key(manifest: dict, bundle: dict) -> str:
    return f"{storage_settings(manifest)['prefix'].rstrip('/')}/{bundle['object']}"


def object_url(config: StorageConfig, key: str) -> str:
    scheme = "cos" if config.provider == "tencent-cos" else "obs"
    return f"{scheme}://{config.bucket}/{key}"


def response_header(response, name: str) -> str | None:
    wanted = name.lower()
    for key, value in response.header or []:
        if str(key).lower() == wanted:
            return str(value)
    return None


def fetch_bundle(manifest: dict, name: str) -> Path:
    bundle = manifest["bundles"][name]
    root = cache_root(manifest)
    downloads = root / ".downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / str(bundle["object"])
    checkpoint = archive.with_suffix(archive.suffix + ".checkpoint")
    config = storage_config(manifest)
    key = object_key(manifest, bundle)
    if config.provider == "tencent-cos":
        from qcloud_cos.cos_exception import CosClientError, CosServiceError
        client = cos_client(config)
        try:
            client.download_file(
                Bucket=config.bucket,
                Key=key,
                DestFilePath=str(archive),
                PartSize=20,
                MAXThread=4,
                EnableCRC=False,
            )
        except (CosServiceError, CosClientError) as error:
            raise TestDataError(f"COS download failed for {name}: {object_url(config, key)}: {error}") from error
    else:
        client = obs_client(config)
        try:
            response = client.downloadFile(
                config.bucket,
                key,
                str(archive),
                partSize=20 * 1024 * 1024,
                taskNum=4,
                enableCheckpoint=True,
                checkpointFile=str(checkpoint),
            )
        finally:
            client.close()
        if response.status >= 300:
            raise TestDataError(
                f"OBS download failed for {name}: status={response.status} code={response.errorCode}"
            )
    verify_archive(archive, bundle)
    extract_archive(archive, root, bundle)
    archive.unlink()
    checkpoint.unlink(missing_ok=True)
    return bundle_dir(manifest, name)


def verify_bundle(manifest: dict, name: str) -> Path:
    bundle = manifest["bundles"][name]
    root = bundle_dir(manifest, name)
    if not root.is_dir():
        raise TestDataError(f"bundle {name} is missing; run test_data.py fetch {name}")
    required = [root / item for item in bundle.get("required_paths", [])]
    missing = [str(path.relative_to(root)) for path in required if not path.exists()]
    if missing:
        raise TestDataError(f"bundle {name} is incomplete: {', '.join(missing)}")
    return root


def publish_bundle(manifest: dict, name: str, archive: Path) -> None:
    bundle = manifest["bundles"][name]
    verify_archive(archive, bundle)
    config = storage_config(manifest)
    key = object_key(manifest, bundle)
    if config.provider == "tencent-cos":
        from qcloud_cos.cos_exception import CosServiceError
        client = cos_client(config)
        try:
            existing = client.head_object(Bucket=config.bucket, Key=key)
        except CosServiceError as error:
            if error.get_status_code() != 404:
                raise TestDataError(
                    f"cannot inspect COS object {object_url(config, key)}: status={error.get_status_code()} code={error.get_error_code()}"
                ) from error
            existing = None
        if existing is not None:
            remote_size = int(existing.get("Content-Length", -1))
            if remote_size == archive.stat().st_size:
                raise TestDataError(f"COS object already exists: {object_url(config, key)}")
            raise TestDataError(f"refusing to replace COS object with different size: {object_url(config, key)}")
        try:
            client.upload_file(
                Bucket=config.bucket,
                Key=key,
                LocalFilePath=str(archive),
                PartSize=100,
                MAXThread=4,
                Metadata={"x-cos-meta-sha256": str(bundle["sha256"])},
            )
        except CosServiceError as error:
            raise TestDataError(f"COS upload failed for {name}: status={error.get_status_code()} code={error.get_error_code()}") from error
        return
    client = obs_client(config)
    try:
        existing = client.getObjectMetadata(config.bucket, key)
        if existing.status < 300:
            content_length = response_header(existing, "content-length")
            if content_length is None:
                raise TestDataError(f"OBS object metadata has no content-length: {key}")
            remote_size = int(content_length)
            if remote_size == archive.stat().st_size:
                raise TestDataError(f"OBS object already exists: obs://{config.bucket}/{key}")
            raise TestDataError(
                f"refusing to replace OBS object with different size: obs://{config.bucket}/{key}"
            )
        if existing.status != 404:
            raise TestDataError(
                f"cannot inspect OBS object: status={existing.status} code={existing.errorCode}"
            )
        checkpoint = archive.with_suffix(archive.suffix + ".upload-checkpoint")
        response = client.uploadFile(
            config.bucket,
            key,
            str(archive),
            partSize=100 * 1024 * 1024,
            taskNum=4,
            enableCheckpoint=True,
            checkpointFile=str(checkpoint),
        )
    finally:
        client.close()
    if response.status >= 300:
        raise TestDataError(
            f"OBS upload failed for {name}: status={response.status} code={response.errorCode}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list")
    for command in ("fetch", "verify"):
        child = subparsers.add_parser(command)
        child.add_argument("bundles", nargs="+", help="bundle names/aliases, or 'all' for current bundles")
    publish = subparsers.add_parser("publish")
    publish.add_argument("bundle")
    publish.add_argument("archive", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = load_manifest(args.manifest)
        if args.command == "list":
            for name, bundle in sorted(manifest["bundles"].items()):
                aliases = ",".join(bundle.get("aliases", [])) or "-"
                print(
                    f"{name}\t{bundle.get('status', 'current')}\t{bundle['size']}\t"
                    f"{bundle['license']}\t{bundle['description']}\taliases={aliases}"
                )
            for name, entry in sorted(manifest.get("catalog", {}).items()):
                scheme = "cos" if entry.get("provider") == "tencent-cos" else "obs"
                print(
                    f"{name}\tcatalog-only\t{scheme}://{entry['bucket']}/{entry['object_key']}\t"
                    f"{entry['size']}\t{entry['description']}\tmanual download; see asr/test-data/README.md"
                )
            return 0
        if args.command == "publish":
            name, = selected_bundle_names(manifest, [args.bundle])
            publish_bundle(manifest, name, args.archive.expanduser().resolve())
            print(f"published {name}")
            return 0
        names = selected_bundle_names(manifest, args.bundles)
        action = fetch_bundle if args.command == "fetch" else verify_bundle
        completed = "fetched" if args.command == "fetch" else "verified"
        for name in names:
            result = action(manifest, name)
            print(f"{completed} {name}: {result}")
        return 0
    except (OSError, TestDataError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
