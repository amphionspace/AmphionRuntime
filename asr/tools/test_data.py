#!/usr/bin/env python3
"""Fetch, verify, and publish versioned test-data bundles stored in OBS."""

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
class ObsConfig:
    bucket: str
    endpoint: str
    access_key: str
    secret_key: str


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TestDataError(f"cannot read test-data manifest {path}: {error}") from error
    if manifest.get("schema_version") != 1:
        raise TestDataError("unsupported test-data manifest schema")
    if not isinstance(manifest.get("bundles"), dict):
        raise TestDataError("test-data manifest bundles must be an object")
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
    if names == ["all"]:
        return sorted(manifest["bundles"])
    unknown = sorted(set(names) - set(manifest["bundles"]))
    if unknown:
        raise TestDataError(f"unknown test-data bundle(s): {', '.join(unknown)}")
    return names


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


def obs_config(manifest: dict) -> ObsConfig:
    settings = manifest["obs"]
    values = {}
    for field, key in (
        ("endpoint", settings["endpoint_env"]),
        ("access_key", settings["access_key_env"]),
        ("secret_key", settings["secret_key_env"]),
    ):
        value = os.environ.get(key)
        if not value:
            raise TestDataError(f"missing OBS environment variable: {key}")
        values[field] = value
    return ObsConfig(bucket=settings["bucket"], **values)


def obs_client(config: ObsConfig):
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


def object_key(manifest: dict, bundle: dict) -> str:
    return f"{manifest['obs']['prefix'].rstrip('/')}/{bundle['object']}"


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
    config = obs_config(manifest)
    client = obs_client(config)
    try:
        response = client.downloadFile(
            config.bucket,
            object_key(manifest, bundle),
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
    config = obs_config(manifest)
    key = object_key(manifest, bundle)
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
        child.add_argument("bundles", nargs="+", help="bundle names or 'all'")
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
                print(f"{name}\t{bundle['size']}\t{bundle['license']}\t{bundle['description']}")
            return 0
        if args.command == "publish":
            selected_bundle_names(manifest, [args.bundle])
            publish_bundle(manifest, args.bundle, args.archive.expanduser().resolve())
            print(f"published {args.bundle}")
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
