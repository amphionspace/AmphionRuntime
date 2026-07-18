#!/usr/bin/env python3
"""Convert one ONNX model to an ARM CPU ORT model with a content cache.

The output is built with the same ONNX Runtime version used by the Harmony
native runtime. Conversion happens in a temporary directory and both the
cache entry and requested output are published atomically.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


REQUIRED_ONNXRUNTIME_VERSION = "1.16.3"
REQUIRED_ONNX_VERSION = "1.15.0"
REQUIRED_NUMPY_VERSION = "1.26.4"
CONVERTER_ID = "onnxruntime-1.16.3-fixed-arm-cpu-v1"
CONVERTER_CONFIG = {
    "id": CONVERTER_ID,
    "onnxruntime_version": REQUIRED_ONNXRUNTIME_VERSION,
    "onnx_version": REQUIRED_ONNX_VERSION,
    "numpy_version": REQUIRED_NUMPY_VERSION,
    "optimization_style": "Fixed",
    "graph_optimization_level": "all",
    "target_platform": "arm",
    "execution_provider": "CPUExecutionProvider",
    # ONNX Runtime 1.16.3's converter applies this filter for target_platform=arm.
    "disabled_optimizers": ["NchwcTransformer"],
}
COPY_CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(COPY_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(COPY_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cache_key(source_sha256: str) -> str:
    payload = {
        "source_sha256": source_sha256,
        "converter": CONVERTER_CONFIG,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as input_stream:
            shutil.copyfileobj(input_stream, output, COPY_CHUNK_SIZE)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, destination)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _atomic_write_json(payload: dict[str, Any], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, destination)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


@contextmanager
def _cache_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _load_valid_cache(entry_dir: Path, source_sha256: str) -> dict[str, Any] | None:
    model_path = entry_dir / "model.ort"
    metadata_path = entry_dir / "metadata.json"
    if not model_path.is_file() or not metadata_path.is_file():
        return None

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if metadata.get("source_sha256") != source_sha256:
        return None
    if metadata.get("cache_key") != entry_dir.name:
        return None
    if metadata.get("converter_id") != CONVERTER_ID or metadata.get("format") != "ort":
        return None
    if metadata.get("converter") != CONVERTER_CONFIG:
        return None
    if metadata.get("output_size_bytes") != model_path.stat().st_size:
        return None
    if metadata.get("output_sha256") != sha256_file(model_path):
        return None
    return metadata


def _load_converter_dependencies() -> tuple[Any, Any, str]:
    try:
        import numpy
    except ImportError as error:
        raise RuntimeError(
            "numpy is missing; install asr/tools/requirements-harmony-ort.txt"
        ) from error

    if numpy.__version__ != REQUIRED_NUMPY_VERSION:
        raise RuntimeError(
            f"numpy=={REQUIRED_NUMPY_VERSION} is required, found {numpy.__version__}"
        )

    try:
        import onnxruntime as ort
    except ImportError as error:
        raise RuntimeError(
            "onnxruntime is missing; install asr/tools/requirements-harmony-ort.txt"
        ) from error

    if ort.__version__ != REQUIRED_ONNXRUNTIME_VERSION:
        raise RuntimeError(
            f"onnxruntime=={REQUIRED_ONNXRUNTIME_VERSION} is required, found {ort.__version__}"
        )
    if "CPUExecutionProvider" not in ort.get_available_providers():
        raise RuntimeError("onnxruntime CPUExecutionProvider is unavailable")

    try:
        import onnx
        from onnxruntime.tools.convert_onnx_models_to_ort import (
            OptimizationStyle,
            convert_onnx_models_to_ort,
        )
    except ImportError as error:
        raise RuntimeError(
            "ONNX converter dependencies are missing; install "
            "asr/tools/requirements-harmony-ort.txt"
        ) from error
    if onnx.__version__ != REQUIRED_ONNX_VERSION:
        raise RuntimeError(
            f"onnx=={REQUIRED_ONNX_VERSION} is required, found {onnx.__version__}"
        )
    return ort, (OptimizationStyle, convert_onnx_models_to_ort), numpy.__version__


def _convert_uncached(source: Path, work_dir: Path) -> tuple[Path, str]:
    ort, converter_api, numpy_version = _load_converter_dependencies()
    optimization_style, convert_onnx_models_to_ort = converter_api

    optimization_level_variable = "ORT_CONVERT_ONNX_MODELS_TO_ORT_OPTIMIZATION_LEVEL"
    previous_optimization_level = os.environ.get(optimization_level_variable)
    os.environ[optimization_level_variable] = "all"
    try:
        convert_onnx_models_to_ort(
            source,
            output_dir=work_dir,
            optimization_styles=[optimization_style.Fixed],
            target_platform="arm",
            save_optimized_onnx_model=False,
            allow_conversion_failures=False,
            enable_type_reduction=False,
        )
    finally:
        if previous_optimization_level is None:
            os.environ.pop(optimization_level_variable, None)
        else:
            os.environ[optimization_level_variable] = previous_optimization_level
    converted_path = work_dir / source.with_suffix(".ort").name
    if not converted_path.is_file():
        raise RuntimeError(f"converter did not create expected output: {converted_path}")

    # Loading the finished FlatBuffer catches truncated or incompatible cache entries.
    ort.InferenceSession(str(converted_path), providers=["CPUExecutionProvider"])
    return converted_path, numpy_version


def convert_model(
    source: Path,
    output: Path,
    metadata_output: Path,
    cache_dir: Path,
) -> tuple[dict[str, Any], bool]:
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"missing ONNX source model: {source}")
    if source.suffix.lower() != ".onnx":
        raise ValueError(f"source model must end in .onnx: {source}")
    if output.suffix.lower() != ".ort":
        raise ValueError(f"output model must end in .ort: {output}")
    if output.resolve() == source:
        raise ValueError("output model must not overwrite the ONNX source")
    if output.resolve() == metadata_output.resolve():
        raise ValueError("model output and metadata output must be different files")

    source_sha256 = sha256_file(source)
    source_md5 = md5_file(source)
    key = cache_key(source_sha256)
    entry_dir = cache_dir.resolve() / key
    lock_path = cache_dir.resolve() / f"{key}.lock"
    cache_hit = False

    with _cache_lock(lock_path):
        metadata = _load_valid_cache(entry_dir, source_sha256)
        if metadata is None:
            cache_dir.mkdir(parents=True, exist_ok=True)
            temporary_dir = Path(
                tempfile.mkdtemp(prefix=f".{key}.", suffix=".tmp", dir=cache_dir.resolve())
            )
            try:
                converted_path, numpy_version = _convert_uncached(source, temporary_dir)
                cached_model = temporary_dir / "model.ort"
                os.replace(converted_path, cached_model)
                output_sha256 = sha256_file(cached_model)
                metadata = {
                    "cache_key": key,
                    "source_name": source.name,
                    "source_sha256": source_sha256,
                    "output_sha256": output_sha256,
                    "output_size_bytes": cached_model.stat().st_size,
                    "format": "ort",
                    "converter_id": CONVERTER_ID,
                    "converter": CONVERTER_CONFIG,
                    "numpy_version": numpy_version,
                }
                _atomic_write_json(metadata, temporary_dir / "metadata.json")
                if entry_dir.exists():
                    shutil.rmtree(entry_dir)
                os.replace(temporary_dir, entry_dir)
            finally:
                if temporary_dir.exists():
                    shutil.rmtree(temporary_dir)
        else:
            cache_hit = True

        # A content-addressed entry can be shared by equal models with different filenames.
        metadata = dict(metadata)
        metadata["source_name"] = source.name
        metadata["source_md5"] = source_md5
        _atomic_copy(entry_dir / "model.ort", output)
        _atomic_write_json(metadata, metadata_output)

    return metadata, cache_hit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="source ONNX model")
    parser.add_argument("--output", required=True, type=Path, help="destination ORT model")
    parser.add_argument(
        "--metadata-output", required=True, type=Path, help="conversion metadata JSON"
    )
    parser.add_argument("--cache-dir", required=True, type=Path, help="content-addressed cache")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        metadata, cache_hit = convert_model(
            args.input, args.output, args.metadata_output, args.cache_dir
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        raise SystemExit(1) from error

    status = "cache hit" if cache_hit else "converted"
    print(
        f"[OK] {status}: {args.input} -> {args.output} "
        f"sha256={metadata['output_sha256']}"
    )


if __name__ == "__main__":
    main()
