from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


SCRIPT = Path(__file__).parents[1] / "test_data.py"
SPEC = importlib.util.spec_from_file_location("test_data", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class TestDataTest(unittest.TestCase):
    def manifest(self, archive: Path, *, digest: str, size: int) -> dict:
        return {
            "schema_version": 1,
            "dataset_version": "v1",
            "obs": {"prefix": "test"},
            "bundles": {
                "sample": {
                    "object": archive.name,
                    "archive_type": "zip",
                    "archive_root": "sample",
                    "destination": "sample",
                    "sha256": digest,
                    "size": size,
                    "required_paths": ["audio/input.wav"],
                }
            },
        }

    def test_cache_root_can_be_shared_across_machines(self) -> None:
        manifest = {"dataset_version": "v1"}
        with mock.patch.dict(os.environ, {"AMPHION_TEST_DATA_DIR": "/data/amphion"}):
            self.assertEqual(Path("/data/amphion"), MODULE.cache_root(manifest))

    def test_archive_hash_and_required_paths_are_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            archive = workspace / "sample.zip"
            with zipfile.ZipFile(archive, "w") as payload:
                payload.writestr("sample/audio/input.wav", b"pcm")
            digest = MODULE.sha256_file(archive)
            manifest = self.manifest(archive, digest=digest, size=archive.stat().st_size)
            MODULE.verify_archive(archive, manifest["bundles"]["sample"])
            with mock.patch.dict(os.environ, {"AMPHION_TEST_DATA_DIR": str(workspace / "cache")}):
                MODULE.extract_archive(
                    archive, MODULE.cache_root(manifest), manifest["bundles"]["sample"]
                )
                result = MODULE.verify_bundle(manifest, "sample")
            self.assertEqual(b"pcm", (result / "audio/input.wav").read_bytes())

    def test_hash_mismatch_fails_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "sample.zip"
            archive.write_bytes(b"not the expected payload")
            bundle = {"size": archive.stat().st_size, "sha256": "0" * 64}
            with self.assertRaisesRegex(MODULE.TestDataError, "SHA-256 mismatch"):
                MODULE.verify_archive(archive, bundle)

    def test_archive_cannot_escape_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            archive = workspace / "sample.zip"
            with zipfile.ZipFile(archive, "w") as payload:
                payload.writestr("../escape", b"bad")
            bundle = {
                "destination": "sample",
                "archive_type": "zip",
                "archive_root": "sample",
            }
            with self.assertRaisesRegex(MODULE.TestDataError, "escapes destination"):
                MODULE.extract_archive(archive, workspace / "cache", bundle)

    def test_manifest_rejects_unknown_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(json.dumps({"schema_version": 2, "bundles": {}}))
            with self.assertRaisesRegex(MODULE.TestDataError, "unsupported"):
                MODULE.load_manifest(manifest)

    def test_obs_response_headers_are_case_insensitive(self) -> None:
        response = mock.Mock(header=[("ETag", "hash"), ("Content-Length", "42")])

        self.assertEqual("42", MODULE.response_header(response, "content-length"))
        self.assertIsNone(MODULE.response_header(response, "missing"))


if __name__ == "__main__":
    unittest.main()
