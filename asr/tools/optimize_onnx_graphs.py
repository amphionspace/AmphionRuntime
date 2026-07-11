#!/usr/bin/env python3
"""Offline-optimize packed ASR ONNX assets and refresh manifest.json."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from verify_packed_model_assets import EXPECTED_BUNDLES, verify_directory


LEVELS = {
    "disable": "ORT_DISABLE_ALL",
    "basic": "ORT_ENABLE_BASIC",
    "extended": "ORT_ENABLE_EXTENDED",
    "all": "ORT_ENABLE_ALL",
}


@dataclass(frozen=True)
class OptimizeResult:
    path: Path
    tmp_path: Path
    old_size: int
    new_size: int
    old_sha256: str
    new_sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def link_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def iter_expected_onnx(root: Path) -> Iterable[Path]:
    for bundle, names in EXPECTED_BUNDLES.items():
        for name in names:
            if name.endswith(".onnx"):
                yield root / bundle / name


def write_manifest(root: Path) -> None:
    bundles: dict[str, list[dict[str, object]]] = {}
    for bundle, names in EXPECTED_BUNDLES.items():
        entries = []
        for name in names:
            path = root / bundle / name
            entries.append(
                {
                    "name": name,
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        bundles[bundle] = entries

    manifest = {"manifest_version": 1, "bundles": bundles}
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_metadata(path: Path) -> dict[str, str]:
    import onnx

    model = onnx.load(str(path), load_external_data=False)
    return {entry.key: entry.value for entry in model.metadata_props}


def preserve_metadata(source: Path, optimized: Path) -> None:
    import onnx

    source_model = onnx.load(str(source), load_external_data=False)
    optimized_model = onnx.load(str(optimized), load_external_data=False)
    del optimized_model.metadata_props[:]
    for entry in source_model.metadata_props:
        copied = optimized_model.metadata_props.add()
        copied.key = entry.key
        copied.value = entry.value
    onnx.save(optimized_model, str(optimized))


def ensure_runtime_dependencies(skip_metadata_check: bool) -> None:
    try:
        ort_version = metadata.version("onnxruntime")
        numpy_version = metadata.version("numpy")
    except metadata.PackageNotFoundError:
        ort_version = ""
        numpy_version = ""

    if ort_version.startswith(("1.16.", "1.17.")) and numpy_version.startswith("2."):
        raise SystemExit(
            f"onnxruntime {ort_version} is not compatible with numpy {numpy_version}; "
            "install 'numpy<2' in the optimizer venv."
        )

    try:
        import onnxruntime  # noqa: F401
    except ImportError as error:
        raise SystemExit(
            "missing dependency: onnxruntime. Install it in a local venv, "
            "preferably matching the target runtime version."
        ) from error

    if skip_metadata_check:
        return
    try:
        import onnx  # noqa: F401
    except ImportError as error:
        raise SystemExit(
            "missing dependency: onnx. It is used to verify sherpa metadata is "
            "preserved; pass --skip-metadata-check only for emergency diagnostics."
        ) from error


def optimize_one(
    path: Path,
    *,
    level: str,
    providers: list[str],
    skip_metadata_check: bool,
) -> OptimizeResult:
    import onnxruntime as ort

    if not path.is_file():
        raise FileNotFoundError(path)

    old_size = path.stat().st_size
    old_sha = sha256_file(path)
    original_metadata = {} if skip_metadata_check else load_metadata(path)
    tmp = path.with_name(f".{path.name}.optimized.tmp")
    if tmp.exists():
        tmp.unlink()

    try:
        options = ort.SessionOptions()
        options.graph_optimization_level = getattr(ort.GraphOptimizationLevel, LEVELS[level])
        options.optimized_model_filepath = str(tmp)
        ort.InferenceSession(str(path), sess_options=options, providers=providers)
        if not tmp.is_file() or tmp.stat().st_size <= 0:
            raise RuntimeError(f"ONNX Runtime did not write optimized model: {tmp}")

        if not skip_metadata_check and load_metadata(tmp) != original_metadata:
            preserve_metadata(path, tmp)
            if load_metadata(tmp) != original_metadata:
                raise RuntimeError(f"metadata changed after optimization: {path}")

        validate_options = ort.SessionOptions()
        validate_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
        ort.InferenceSession(str(tmp), sess_options=validate_options, providers=providers)

        new_size = tmp.stat().st_size
        new_sha = sha256_file(tmp)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise

    return OptimizeResult(path, tmp, old_size, new_size, old_sha, new_sha)


def cleanup_result_temps(results: Iterable[OptimizeResult]) -> None:
    for result in results:
        if result.tmp_path.exists():
            result.tmp_path.unlink()


def publish_results(root: Path, results: list[OptimizeResult], backup_dir: Path | None) -> None:
    manifest_path = root / "manifest.json"
    with tempfile.TemporaryDirectory(prefix=".onnx-opt-rollback-", dir=root) as rollback_temp:
        rollback_root = Path(rollback_temp)
        if manifest_path.exists():
            link_or_copy(manifest_path, rollback_root / "manifest.json")
        for result in results:
            link_or_copy(result.path, rollback_root / result.path.relative_to(root))

        try:
            if backup_dir is not None:
                for result in results:
                    backup_path = backup_dir / result.path.relative_to(root)
                    backup_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(result.path, backup_path)
            for result in results:
                result.tmp_path.replace(result.path)
            write_manifest(root)
            verify_directory(root)
        except Exception:
            for result in results:
                rollback_path = rollback_root / result.path.relative_to(root)
                if rollback_path.exists():
                    shutil.copy2(rollback_path, result.path)
            rollback_manifest = rollback_root / "manifest.json"
            if rollback_manifest.exists():
                shutil.copy2(rollback_manifest, manifest_path)
            raise
        finally:
            cleanup_result_temps(results)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="amphion-models directory")
    parser.add_argument(
        "--level",
        choices=sorted(LEVELS),
        default="extended",
        help=(
            "ONNX Runtime graph optimization level. Default is extended; all can "
            "emit host/provider-specific layout transforms."
        ),
    )
    parser.add_argument(
        "--provider",
        action="append",
        default=None,
        help="ONNX Runtime execution provider. May be passed more than once.",
    )
    parser.add_argument("--backup-dir", type=Path, help="copy originals here before replacing")
    parser.add_argument("--dry-run", action="store_true", help="write temp optimized models, then discard them")
    parser.add_argument(
        "--skip-metadata-check",
        action="store_true",
        help="do not require onnx or compare model metadata",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    providers = args.provider or ["CPUExecutionProvider"]

    ensure_runtime_dependencies(args.skip_metadata_check)
    verify_directory(root)

    backup_dir = args.backup_dir.resolve() if args.backup_dir is not None else None
    if backup_dir is not None and not args.dry_run:
        backup_dir.mkdir(parents=True, exist_ok=True)

    results = []
    try:
        for path in iter_expected_onnx(root):
            results.append(
                optimize_one(
                    path,
                    level=args.level,
                    providers=providers,
                    skip_metadata_check=args.skip_metadata_check,
                )
            )

        if args.dry_run:
            cleanup_result_temps(results)
        else:
            publish_results(root, results, backup_dir)
    except Exception:
        cleanup_result_temps(results)
        raise

    for result in results:
        rel = result.path.relative_to(root)
        delta = result.new_size - result.old_size
        print(
            f"[OK] {rel}: {result.old_size} -> {result.new_size} bytes "
            f"({delta:+d}), sha {result.old_sha256[:12]} -> {result.new_sha256[:12]}"
        )


if __name__ == "__main__":
    main()
