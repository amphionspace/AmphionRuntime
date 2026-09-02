#!/usr/bin/env python3
"""Synchronize versioned, Git-external collaboration assets with Huawei OBS."""

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
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Optional


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_MANIFEST = SCRIPT_DIR / "manifest.json"
DEFAULT_DOWNLOAD_ROOT = Path.home() / ".cache" / "amphion-runtime" / "assets"


class AssetError(RuntimeError):
    pass


@dataclass(frozen=True)
class Storage:
    bucket: str
    endpoint_env: str
    access_key_env: str
    secret_key_env: str
    prefix: str


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


def read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AssetError(f"cannot read asset manifest {path}: {error}") from error
    if payload.get("schema_version") != 1:
        raise AssetError(f"unsupported asset manifest schema in {path}")
    return payload


def storage_from(payload: dict) -> Storage:
    settings = payload.get("storage") or payload.get("obs")
    if not isinstance(settings, dict):
        raise AssetError("asset manifest storage must be an object")
    return Storage(
        bucket=str(settings["bucket"]),
        endpoint_env=str(settings["endpoint_env"]),
        access_key_env=str(settings["access_key_env"]),
        secret_key_env=str(settings["secret_key_env"]),
        prefix=str(settings["prefix"]),
    )


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


def load_registry(manifest_path: Path, repo_root: Path) -> tuple[dict, dict[str, Bundle]]:
    manifest = read_json(manifest_path)
    storage = storage_from(manifest)
    raw_bundles = manifest.get("bundles")
    if not isinstance(raw_bundles, dict):
        raise AssetError("asset manifest bundles must be an object")
    bundles: dict[str, Bundle] = {}
    for name, definition in raw_bundles.items():
        validate_bundle(name, definition)
        bundles[name] = Bundle(name, definition, storage, repo_root, True)

    for include in manifest.get("included_manifests", []):
        include_path = safe_join(repo_root, str(include["path"]))
        included = read_json(include_path)
        if include.get("kind") != "test-data":
            raise AssetError(f"unsupported included manifest kind: {include.get('kind')}")
        included_storage = storage_from(included)
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
    if names == ["all"]:
        return [bundles[name] for name in sorted(bundles)]
    unknown = sorted(set(names) - set(bundles))
    if unknown:
        raise AssetError(f"unknown asset bundle(s): {', '.join(unknown)}")
    return [bundles[name] for name in names]


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
    if bundle.definition.get("encryption") == "sse-kms":
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
    if bundle.definition.get("encryption") == "sse-kms":
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


def obs_client(storage: Storage):
    values = {}
    for field, env_name in (
        ("endpoint", storage.endpoint_env),
        ("access_key", storage.access_key_env),
        ("secret_key", storage.secret_key_env),
    ):
        value = os.environ.get(env_name)
        if not value:
            raise AssetError(f"missing OBS environment variable: {env_name}")
        values[field] = value
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


def response_header(response, name: str) -> Optional[str]:
    wanted = name.lower()
    for key, value in response.header or []:
        if str(key).lower() == wanted:
            return str(value)
    return None


def remote_identity(bundle: Bundle) -> tuple[int, Optional[str], Optional[str]]:
    client = obs_client(bundle.storage)
    try:
        response = client.getObjectMetadata(bundle.storage.bucket, bundle.object_key)
    finally:
        client.close()
    if response.status >= 300:
        raise AssetError(
            f"cannot inspect OBS object for {bundle.name}: "
            f"status={response.status} code={response.errorCode}"
        )
    content_length = response_header(response, "content-length")
    if content_length is None:
        raise AssetError(f"OBS object has no content-length: {bundle.object_key}")
    metadata_hash = response_header(response, "x-obs-meta-sha256")
    encryption = getattr(response.body, "sseKms", None)
    return int(content_length), metadata_hash, encryption


def verify_remote(bundle: Bundle) -> None:
    size, metadata_hash, encryption = remote_identity(bundle)
    if size != int(bundle.definition["size"]):
        raise AssetError(
            f"remote size mismatch for {bundle.name}: expected {bundle.definition['size']}, got {size}"
        )
    if metadata_hash and metadata_hash != bundle.definition["sha256"]:
        raise AssetError(
            f"remote SHA-256 metadata mismatch for {bundle.name}: "
            f"expected {bundle.definition['sha256']}, got {metadata_hash}"
        )
    if bundle.definition.get("encryption") == "sse-kms" and encryption != "kms":
        raise AssetError(f"remote object for {bundle.name} is not encrypted with SSE-KMS")


def download_root() -> Path:
    configured = os.environ.get("AMPHION_ASSET_CACHE_DIR")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_DOWNLOAD_ROOT


def fetch_bundle(bundle: Bundle, *, replace_existing: bool = False) -> Path:
    try:
        return verify_local(bundle)
    except AssetError:
        pass
    restricted = bundle.definition.get("encryption") == "sse-kms"
    downloads = download_root() / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    if restricted:
        os.chmod(downloads, 0o700)
    archive = downloads / f"{bundle.name}-{bundle.definition['sha256']}.zip"
    checkpoint = archive.with_suffix(".zip.checkpoint")
    try:
        if not archive.exists():
            client = obs_client(bundle.storage)
            try:
                response = client.downloadFile(
                    bundle.storage.bucket,
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
                    f"OBS download failed for {bundle.name}: "
                    f"status={response.status} code={response.errorCode}"
                )
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
            checkpoint.unlink(missing_ok=True)


def publish_bundle(bundle: Bundle) -> str:
    if not bundle.owned:
        raise AssetError(f"included bundle {bundle.name} is published by its owning tool")
    restricted = bundle.definition.get("encryption") == "sse-kms"
    downloads = download_root() / "uploads"
    downloads.mkdir(parents=True, exist_ok=True)
    if restricted:
        os.chmod(downloads, 0o700)
    archive = downloads / f"{bundle.name}-{bundle.definition['sha256']}.zip"
    checkpoint = archive.with_suffix(".zip.upload-checkpoint")
    headers = None
    if restricted:
        try:
            from obs import PutObjectHeader, SseKmsHeader
        except ImportError as error:
            raise AssetError(
                "missing Huawei OBS SDK; run: python3 -m pip install esdk-obs-python"
            ) from error
        headers = PutObjectHeader(sseHeader=SseKmsHeader.getInstance())
    try:
        build_archive(bundle, archive)
        if restricted:
            os.chmod(archive, 0o600)
        client = obs_client(bundle.storage)
        try:
            existing = client.getObjectMetadata(bundle.storage.bucket, bundle.object_key)
            if existing.status < 300:
                content_length = response_header(existing, "content-length")
                metadata_hash = response_header(existing, "x-obs-meta-sha256")
                if content_length != str(bundle.definition["size"]):
                    raise AssetError(
                        f"refusing to replace OBS object with different size: {bundle.object_key}"
                    )
                if metadata_hash and metadata_hash != bundle.definition["sha256"]:
                    raise AssetError(
                        f"refusing to replace OBS object with different SHA-256: {bundle.object_key}"
                    )
                if restricted and getattr(existing.body, "sseKms", None) != "kms":
                    raise AssetError(
                        f"refusing unencrypted existing restricted object: {bundle.object_key}"
                    )
                archive.unlink()
                return "already-present"
            if existing.status != 404:
                raise AssetError(
                    f"cannot inspect OBS object for {bundle.name}: "
                    f"status={existing.status} code={existing.errorCode}"
                )
            response = client.uploadFile(
                bundle.storage.bucket,
                bundle.object_key,
                str(archive),
                partSize=20 * 1024 * 1024,
                taskNum=4,
                enableCheckpoint=not restricted,
                checkpointFile=None if restricted else str(checkpoint),
                metadata={"sha256": bundle.definition["sha256"]},
                headers=headers,
            )
        finally:
            client.close()
        if response.status >= 300:
            raise AssetError(
                f"OBS upload failed for {bundle.name}: "
                f"status={response.status} code={response.errorCode}"
            )
        verify_remote(bundle)
        archive.unlink()
        checkpoint.unlink(missing_ok=True)
        return "uploaded"
    finally:
        if restricted:
            archive.unlink(missing_ok=True)
            checkpoint.unlink(missing_ok=True)


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
    fetch.add_argument("bundles", nargs="+", help="bundle names or 'all'")
    fetch.add_argument(
        "--replace-existing",
        action="store_true",
        help="replace conflicting files in merge-style restricted bundles",
    )
    for command in ("verify", "remote-verify", "publish"):
        child = commands.add_parser(command)
        child.add_argument("bundles", nargs="+", help="bundle names or 'all'")
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
                print(
                    f"{name}\t{scope}\t{bundle.definition['size']}\t"
                    f"{bundle.definition['license']}\t{bundle.definition['description']}"
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
        return 0
    except (AssetError, OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
