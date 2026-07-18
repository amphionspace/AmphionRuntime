from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import convert_harmony_ort as converter  # noqa: E402


class ConvertHarmonyOrtTest(unittest.TestCase):
    def test_conversion_forces_all_optimization_and_restores_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "model.onnx"
            source.write_bytes(b"source")
            work_dir = root / "work"
            work_dir.mkdir()
            observed_level = []

            class FakeOrt:
                @staticmethod
                def InferenceSession(*args: object, **kwargs: object) -> object:
                    return object()

            class FakeOptimizationStyle:
                Fixed = object()

            def fake_convert(*args: object, **kwargs: object) -> None:
                observed_level.append(
                    os.environ.get("ORT_CONVERT_ONNX_MODELS_TO_ORT_OPTIMIZATION_LEVEL")
                )
                (work_dir / "model.ort").write_bytes(b"converted")

            with mock.patch.dict(
                "os.environ",
                {"ORT_CONVERT_ONNX_MODELS_TO_ORT_OPTIMIZATION_LEVEL": "basic"},
            ), mock.patch.object(
                converter,
                "_load_converter_dependencies",
                return_value=(
                    FakeOrt,
                    (FakeOptimizationStyle, fake_convert),
                    "1.26.4",
                ),
            ):
                converted, numpy_version = converter._convert_uncached(source, work_dir)
                self.assertEqual(
                    os.environ["ORT_CONVERT_ONNX_MODELS_TO_ORT_OPTIMIZATION_LEVEL"],
                    "basic",
                )

            self.assertEqual(observed_level, ["all"])
            self.assertEqual(converted.read_bytes(), b"converted")
            self.assertEqual(numpy_version, "1.26.4")

    def test_cache_hit_is_content_verified_and_skips_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "decoder.int8.onnx"
            source.write_bytes(b"source-model")
            source_sha256 = converter.sha256_file(source)
            key = converter.cache_key(source_sha256)
            entry = root / "cache" / key
            entry.mkdir(parents=True)
            cached_model = entry / "model.ort"
            cached_model.write_bytes(b"converted-model")
            metadata = {
                "cache_key": key,
                "source_name": source.name,
                "source_sha256": source_sha256,
                "output_sha256": converter.sha256_file(cached_model),
                "output_size_bytes": cached_model.stat().st_size,
                "format": "ort",
                "converter_id": converter.CONVERTER_ID,
                "converter": converter.CONVERTER_CONFIG,
                "numpy_version": "1.26.4",
            }
            (entry / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

            output = root / "output" / "decoder.int8.ort"
            metadata_output = root / "output" / "decoder.metadata.json"
            with mock.patch.object(
                converter, "_convert_uncached", side_effect=AssertionError("cache miss")
            ):
                result, cache_hit = converter.convert_model(
                    source, output, metadata_output, root / "cache"
                )

            self.assertTrue(cache_hit)
            self.assertEqual(output.read_bytes(), b"converted-model")
            self.assertEqual(result["source_md5"], converter.md5_file(source))
            self.assertEqual(result["output_sha256"], converter.sha256_file(output))
            self.assertEqual(json.loads(metadata_output.read_text()), result)

    def test_corrupt_cache_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "model.onnx"
            source.write_bytes(b"source-model")
            source_sha256 = converter.sha256_file(source)
            entry = root / converter.cache_key(source_sha256)
            entry.mkdir()
            (entry / "model.ort").write_bytes(b"corrupt")
            (entry / "metadata.json").write_text(
                json.dumps(
                    {
                        "source_sha256": source_sha256,
                        "output_sha256": "0" * 64,
                        "output_size_bytes": 7,
                        "converter": converter.CONVERTER_CONFIG,
                    }
                ),
                encoding="utf-8",
            )

            self.assertIsNone(converter._load_valid_cache(entry, source_sha256))


if __name__ == "__main__":
    unittest.main()
