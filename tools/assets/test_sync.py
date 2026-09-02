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


MODULE_PATH = Path(__file__).with_name("sync.py")
SPEC = importlib.util.spec_from_file_location("asset_sync", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class AssetSyncTest(unittest.TestCase):
    def bundle(self, root: Path, *, digest: str, size: int) -> MODULE.Bundle:
        definition = {
            "description": "fixture",
            "license": "test",
            "redistribution": "test-only",
            "destination": "assets/sample",
            "archive_root": "sample",
            "archive_type": "zip",
            "object": "sample.zip",
            "size": size,
            "sha256": digest,
            "files": [
                {
                    "path": "model.bin",
                    "size": 7,
                    "sha256": MODULE.hashlib.sha256(b"payload").hexdigest(),
                }
            ],
        }
        storage = MODULE.Storage("bucket", "ENDPOINT", "ACCESS", "SECRET", "test")
        return MODULE.Bundle("sample", definition, storage, root, True)

    def restricted_bundle(self, root: Path) -> MODULE.Bundle:
        payload = b"private"
        definition = {
            "description": "restricted fixture",
            "license": "confidential",
            "redistribution": "test-only",
            "destination": ".secure",
            "archive_root": "secure",
            "archive_type": "zip",
            "object": "secure.zip",
            "size": 1,
            "sha256": "0" * 64,
            "encryption": "sse-kms",
            "merge_destination": True,
            "allow_extra_files": True,
            "files": [
                {
                    "path": "private.pem",
                    "size": len(payload),
                    "sha256": MODULE.hashlib.sha256(payload).hexdigest(),
                    "mode": "0600",
                }
            ],
        }
        storage = MODULE.Storage("bucket", "ENDPOINT", "ACCESS", "SECRET", "test")
        return MODULE.Bundle("restricted", definition, storage, root, True)

    def test_archive_is_deterministic_and_restores_exact_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "assets/sample"
            source.mkdir(parents=True)
            (source / "model.bin").write_bytes(b"payload")
            provisional = self.bundle(root, digest="0" * 64, size=1)
            first = root / "first.zip"
            second = root / "second.zip"
            with mock.patch.object(MODULE, "verify_archive"):
                MODULE.build_archive(provisional, first)
                MODULE.build_archive(provisional, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())

            bundle = self.bundle(
                root,
                digest=MODULE.sha256_file(first),
                size=first.stat().st_size,
            )
            MODULE.verify_archive(first, bundle)
            for item in source.iterdir():
                item.unlink()
            source.rmdir()
            with tempfile.TemporaryDirectory(dir=root) as stage:
                extracted = MODULE.safe_extract(first, Path(stage), bundle)
                MODULE.replace_destination(extracted, bundle.destination)
            self.assertEqual(b"payload", MODULE.verify_local(bundle).joinpath("model.bin").read_bytes())

    def test_archive_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "bad.zip"
            with zipfile.ZipFile(archive, "w") as payload:
                payload.writestr("../escape", b"bad")
            bundle = self.bundle(root, digest=MODULE.sha256_file(archive), size=archive.stat().st_size)
            with self.assertRaisesRegex(MODULE.AssetError, "escapes"):
                MODULE.safe_extract(archive, root / "stage", bundle)

    def test_archive_restores_executable_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "assets/sample"
            source.mkdir(parents=True)
            executable = source / "model.bin"
            executable.write_bytes(b"payload")
            executable.chmod(0o755)
            bundle = self.bundle(root, digest="0" * 64, size=1)
            bundle.definition["files"][0]["mode"] = "0755"
            archive = root / "executable.zip"
            with mock.patch.object(MODULE, "verify_archive"):
                MODULE.build_archive(bundle, archive)
            with tempfile.TemporaryDirectory(dir=root) as stage:
                extracted = MODULE.safe_extract(archive, Path(stage), bundle)
                self.assertEqual(0o755, (extracted / "model.bin").stat().st_mode & 0o777)

    def test_local_verification_rejects_unlisted_asset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "assets/sample"
            source.mkdir(parents=True)
            (source / "model.bin").write_bytes(b"payload")
            (source / "unexpected.bin").write_bytes(b"extra")
            bundle = self.bundle(root, digest="0" * 64, size=1)
            with self.assertRaisesRegex(MODULE.AssetError, "unexpected"):
                MODULE.verify_local(bundle)

    def test_restricted_merge_preserves_extra_files_and_refuses_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / ".secure"
            destination.mkdir()
            (destination / "local-only.txt").write_bytes(b"keep")
            extracted = root / "extracted"
            extracted.mkdir()
            (extracted / "private.pem").write_bytes(b"private")
            bundle = self.restricted_bundle(root)

            MODULE.merge_destination(extracted, bundle)
            self.assertEqual(b"keep", (destination / "local-only.txt").read_bytes())
            self.assertEqual(b"private", (destination / "private.pem").read_bytes())
            self.assertEqual(0o600, (destination / "private.pem").stat().st_mode & 0o777)

            (destination / "private.pem").write_bytes(b"different")
            with self.assertRaisesRegex(MODULE.AssetError, "--replace-existing"):
                MODULE.merge_destination(extracted, bundle)

    def test_restricted_remote_requires_kms_marker(self) -> None:
        bundle = self.restricted_bundle(Path("/tmp/repo"))
        with mock.patch.object(MODULE, "remote_identity", return_value=(1, None, None)):
            with self.assertRaisesRegex(MODULE.AssetError, "SSE-KMS"):
                MODULE.verify_remote(bundle)

    def test_audit_rejects_unclassified_ignored_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self.bundle(root, digest="0" * 64, size=1)
            manifest = {"ignored_asset_policy": {"excluded": []}}
            with mock.patch.object(MODULE, "ignored_files", return_value=["private/model.onnx"]):
                with self.assertRaisesRegex(MODULE.AssetError, "unclassified"):
                    MODULE.audit_ignored(root, manifest, {bundle.name: bundle})

    def test_audit_unions_versioned_bundles_with_the_same_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = self.restricted_bundle(root)
            current = self.restricted_bundle(root)
            current.definition["files"] = [
                {
                    "path": "material/current.bin",
                    "size": 7,
                    "sha256": MODULE.hashlib.sha256(b"payload").hexdigest(),
                }
            ]
            manifest = {"ignored_asset_policy": {"excluded": []}}
            ignored = [".secure/material/current.bin"]
            with mock.patch.object(MODULE, "ignored_files", return_value=ignored):
                counts = MODULE.audit_ignored(
                    root,
                    manifest,
                    {"secure-v1": old, "secure-v2": current},
                )
            self.assertEqual({"synchronized": 1}, counts)

    def test_generated_frontend_dictionaries_are_classified_narrowly(self) -> None:
        manifest = json.loads(MODULE.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
        generated = [
            "tts/android/external-resources/tts/model/1.0/chinese_lexicon.bin",
            "tts/android/external-resources/tts/model/1.0/cmudict.bin",
            "tts/tools/trial-export/model/1.0/chinese_lexicon.bin",
            "tts/tools/trial-export/model/1.0/cmudict.bin",
            "asr/harmony/sdk-dingqiao/src/main/resources/rawfile/"
            "amphion-dingqiao/eres2net.onnx",
            "asr/harmony/sdk-dingqiao/src/main/resources/rawfile/"
            "amphion-dingqiao/pyannote-segmentation-3.0.LICENSE",
            "asr/harmony/sdk-dingqiao/src/main/resources/rawfile/"
            "amphion-dingqiao/pyannote-segmentation-3.0.onnx",
            "asr/harmony/sdk-police/src/main/resources/rawfile/"
            "amphion-police/lac/v1/lac_encoder.onnx",
        ]
        for path in generated:
            with self.subTest(path=path):
                self.assertEqual("generated-output", MODULE.policy_match(path, manifest))
        self.assertIsNone(MODULE.policy_match("private/model.bin", manifest))

    def test_test_data_include_uses_shared_cache_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tools/assets").mkdir(parents=True)
            (root / "asr/test-data").mkdir(parents=True)
            manifest = {
                "schema_version": 1,
                "storage": {
                    "bucket": "bucket",
                    "endpoint_env": "ENDPOINT",
                    "access_key_env": "ACCESS",
                    "secret_key_env": "SECRET",
                    "prefix": "assets",
                },
                "bundles": {},
                "included_manifests": [
                    {"path": "asr/test-data/manifest.json", "kind": "test-data"}
                ],
            }
            test_data = {
                "schema_version": 1,
                "dataset_version": "v1",
                "obs": {
                    "bucket": "bucket",
                    "endpoint_env": "ENDPOINT",
                    "access_key_env": "ACCESS",
                    "secret_key_env": "SECRET",
                    "prefix": "test-data/v1",
                },
                "bundles": {
                    "corpus": {
                        "description": "fixture",
                        "license": "test",
                        "redistribution": "test-only",
                        "destination": "corpus",
                        "archive_root": "corpus",
                        "archive_type": "zip",
                        "object": "corpus.zip",
                        "size": 1,
                        "sha256": "0" * 64,
                    }
                },
            }
            manifest_path = root / "tools/assets/manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (root / "asr/test-data/manifest.json").write_text(
                json.dumps(test_data), encoding="utf-8"
            )
            shared = root / "shared-cache"
            with mock.patch.dict(os.environ, {"AMPHION_TEST_DATA_DIR": str(shared)}):
                _, bundles = MODULE.load_registry(manifest_path, root)
            self.assertEqual(shared.resolve() / "corpus", bundles["corpus"].destination)


if __name__ == "__main__":
    unittest.main()
