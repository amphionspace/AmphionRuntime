from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import build_harmony_asset_manifest as builder  # noqa: E402
import convert_harmony_ort as converter  # noqa: E402
import verify_packed_model_assets as verifier  # noqa: E402


class BuildHarmonyAssetManifestTest(unittest.TestCase):
    def test_generated_manifest_passes_strict_v2_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            root = workspace / "amphion-models"
            sources = workspace / "sources"
            metadata_dir = workspace / "metadata"
            copied: dict[str, Path] = {}
            converted: dict[str, Path] = {}

            for bundle, names in builder.HARMONY_BUNDLES.items():
                for name in names:
                    target = f"{bundle}/{name}"
                    output_path = root / target
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(f"output:{target}".encode())
                    if name.endswith(".ort"):
                        source_name = name.removesuffix(".ort") + ".onnx"
                        source_path = sources / bundle / source_name
                        source_path.parent.mkdir(parents=True, exist_ok=True)
                        source_path.write_bytes(f"source:{target}".encode())
                        metadata_path = metadata_dir / f"{bundle.replace('/', '-')}-{name}.json"
                        metadata_path.parent.mkdir(parents=True, exist_ok=True)
                        metadata_path.write_text(
                            json.dumps(
                                {
                                    "source_name": source_name,
                                    "source_md5": converter.md5_file(source_path),
                                    "source_sha256": converter.sha256_file(source_path),
                                    "output_sha256": converter.sha256_file(output_path),
                                    "output_size_bytes": output_path.stat().st_size,
                                    "converter_id": converter.CONVERTER_ID,
                                    "converter": converter.CONVERTER_CONFIG,
                                    "format": "ort",
                                }
                            ),
                            encoding="utf-8",
                        )
                        converted[target] = metadata_path
                    else:
                        source_path = sources / target
                        source_path.parent.mkdir(parents=True, exist_ok=True)
                        source_path.write_bytes(output_path.read_bytes())
                        copied[target] = source_path

            manifest = builder.build_manifest(root, copied, converted)
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            self.assertEqual(verifier.verify_directory(root), 14)
            encoder = manifest["bundles"]["zh-en/v1"][0]
            self.assertEqual(encoder["format"], "ort")
            self.assertEqual(encoder["converter"], converter.CONVERTER_ID)
            self.assertEqual(
                encoder["source_md5"],
                converter.md5_file(sources / "zh-en/v1/encoder.int8.onnx"),
            )
            self.assertNotEqual(encoder["source_sha256"], encoder["output_sha256"])
            copied["zh-en/v1/tokens.txt"].write_bytes(b"different")
            with self.assertRaisesRegex(ValueError, "copied output differs"):
                builder.build_manifest(root, copied, converted)

    def test_zh_en_only_manifest_omits_yue_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            root = workspace / "amphion-models"
            sources = workspace / "sources"
            metadata_dir = workspace / "metadata"
            copied: dict[str, Path] = {}
            converted: dict[str, Path] = {}
            for bundle, names in builder.HARMONY_BUNDLES.items():
                if bundle == "yue-en/v1":
                    continue
                for name in names:
                    target = f"{bundle}/{name}"
                    output = root / target
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(f"output:{target}".encode())
                    if name.endswith(".ort"):
                        source = sources / bundle / (name.removesuffix(".ort") + ".onnx")
                        source.parent.mkdir(parents=True, exist_ok=True)
                        source.write_bytes(f"source:{target}".encode())
                        metadata = metadata_dir / f"{bundle.replace('/', '-')}-{name}.json"
                        metadata.parent.mkdir(parents=True, exist_ok=True)
                        metadata.write_text(json.dumps({
                            "source_name": source.name,
                            "source_md5": converter.md5_file(source),
                            "source_sha256": converter.sha256_file(source),
                            "output_sha256": converter.sha256_file(output),
                            "output_size_bytes": output.stat().st_size,
                            "converter_id": converter.CONVERTER_ID,
                            "converter": converter.CONVERTER_CONFIG,
                            "format": "ort",
                        }), encoding="utf-8")
                        converted[target] = metadata
                    else:
                        source = sources / target
                        source.parent.mkdir(parents=True, exist_ok=True)
                        source.write_bytes(output.read_bytes())
                        copied[target] = source
            manifest = builder.build_manifest(root, copied, converted, zh_en_only=True)
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertNotIn("yue-en/v1", manifest["bundles"])
            self.assertEqual(verifier.verify_directory(root, zh_en_only=True), 9)


if __name__ == "__main__":
    unittest.main()
