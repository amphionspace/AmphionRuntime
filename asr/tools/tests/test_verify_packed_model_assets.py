from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import verify_packed_model_assets as verifier  # noqa: E402


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def write_fixture(root: Path, version: int) -> dict:
    expected = (
        verifier.EXPECTED_BUNDLES_V1 if version == 1 else verifier.EXPECTED_BUNDLES_V2
    )
    bundles = {}
    for bundle, names in expected.items():
        entries = []
        for name in names:
            data = f"{bundle}/{name}".encode("utf-8")
            destination = root / bundle / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            if version == 1:
                entry = {"name": name, "size_bytes": len(data), "sha256": sha256(data)}
            else:
                output_sha256 = sha256(data)
                converter = (
                    verifier.HARMONY_CONVERTER_ID if name.endswith(".ort") else "copy"
                )
                source_sha256 = (
                    sha256(f"source/{bundle}/{name}".encode("utf-8"))
                    if name.endswith(".ort")
                    else output_sha256
                )
                entry = {
                    "name": name,
                    "size_bytes": len(data),
                    "source_name": name.replace(".ort", ".onnx"),
                    "source_md5": md5(f"source/{bundle}/{name}".encode("utf-8")),
                    "source_sha256": source_sha256,
                    "output_sha256": output_sha256,
                    "format": verifier._expected_v2_format(name),
                    "converter": converter,
                }
            entries.append(entry)
        bundles[bundle] = entries

    manifest = {"manifest_version": version, "bundles": bundles}
    if version == 2:
        manifest.update(
            {
                "target": verifier.EXPECTED_HARMONY_TARGET,
                "converters": {
                    "copy": {"mode": "byte-for-byte"},
                    verifier.HARMONY_CONVERTER_ID: verifier.EXPECTED_HARMONY_CONVERTER,
                },
            }
        )
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


class VerifyPackedModelAssetsTest(unittest.TestCase):
    def test_android_manifest_v1_directory_still_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_fixture(root, 1)
            self.assertEqual(verifier.verify_directory(root), 14)

    def test_android_manifest_v1_archive_still_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            root = workspace / "assets" / "amphion-models"
            write_fixture(root, 1)
            archive = workspace / "sdk.aar"
            with zipfile.ZipFile(archive, "w") as package:
                for path in root.rglob("*"):
                    if path.is_file():
                        package.write(path, path.relative_to(workspace).as_posix())
            self.assertEqual(
                verifier.verify_archive(archive, "assets/amphion-models"), 14
            )

    def test_harmony_manifest_v2_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_fixture(root, 2)
            self.assertEqual(verifier.verify_directory(root), 14)

    def test_harmony_manifest_v2_rejects_legacy_target_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_fixture(root, 2)
            legacy = root / "zh-en/v1/encoder.int8.onnx"
            legacy.write_bytes(b"legacy")
            with self.assertRaisesRegex(ValueError, "Harmony target file mismatch"):
                verifier.verify_directory(root)

    def test_harmony_manifest_v2_requires_source_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manifest = write_fixture(root, 2)
            manifest["bundles"]["zh-en/v1"][0].pop("source_sha256")
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid source_sha256"):
                verifier.verify_directory(root)

    def test_harmony_manifest_v2_requires_source_md5(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manifest = write_fixture(root, 2)
            manifest["bundles"]["zh-en/v1"][0].pop("source_md5")
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid source_md5"):
                verifier.verify_directory(root)


if __name__ == "__main__":
    unittest.main()
