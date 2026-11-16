from __future__ import annotations

import importlib.util
import io
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
    def test_all_selects_current_assets_and_history_remains_addressable(self) -> None:
        _, bundles = MODULE.load_registry(MODULE.DEFAULT_MANIFEST, MODULE.DEFAULT_REPO_ROOT)
        selected = {bundle.name for bundle in MODULE.selected_bundles(bundles, ["all"])}
        self.assertEqual(
            {"team-secure-state-v5"},
            {name for name in selected if name.startswith("team-secure-state-")},
        )
        self.assertIn("asr-itn-zh-v2", selected)
        self.assertNotIn("asr-itn-zh-v1", selected)
        self.assertEqual(
            [bundles["team-secure-state-v2"]],
            MODULE.selected_bundles(bundles, ["team-secure-state-v2"]),
        )

    def test_corpus_alias_reuses_archive_and_cache_without_duplicate_selection(self) -> None:
        _, bundles = MODULE.load_registry(MODULE.DEFAULT_MANIFEST, MODULE.DEFAULT_REPO_ROOT)
        selected = MODULE.selected_bundles(bundles, ["aishell3-500", "aishell3-hotwords-500"])
        self.assertEqual(1, len(selected))
        self.assertEqual("aishell3-500", selected[0].name)
        self.assertEqual("aishell3_test_hotwords_500", selected[0].destination.name)
        self.assertEqual(
            "amphion-runtime/test-data/v1/amphion-test-data-aishell3-hotwords-500-v1.zip",
            selected[0].object_key,
        )

    def test_list_exposes_police_catalog_without_selecting_it_for_fetch_all(self) -> None:
        output = io.StringIO()
        with mock.patch.object(sys, "argv", [MODULE.__file__, "list"]), mock.patch("sys.stdout", output):
            self.assertEqual(0, MODULE.main())
        self.assertIn("police-asr-eval-20260914\tcatalog-only\t", output.getvalue())
        _, bundles = MODULE.load_registry(MODULE.DEFAULT_MANIFEST, MODULE.DEFAULT_REPO_ROOT)
        self.assertNotIn("police-asr-eval-20260914", [b.name for b in MODULE.selected_bundles(bundles, ["all"])])

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
            "tts/android/external-resources/tts/model/1.0/manifest.json",
            "tts/android/external-resources/tts/model/1.0/model.onnx",
            "tts/harmony/sdk/src/main/resources/rawfile/lits-models/tts/"
            "model/1.0/manifest.json",
            "tts/harmony/sdk/src/main/resources/rawfile/lits-models/tts/"
            "model/1.0/model.onnx",
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

    def test_synchronized_repository_assets_are_not_tracked_by_git(self) -> None:
        """外置资产不得再被 Git 跟踪：2026-11-16 起仓库只保留源码，模型/原生库全部由 bundle 恢复。

        以前 `shared/models` 与 `tts/tools/trial-export` 的文件既在 bundle 里又在 Git 里，
        远程仓库因此长到 200 MB。这里对每个仓库内 bundle 的逐文件清单查 `git ls-files`，
        任何一条被跟踪就失败；新增大文件请走 bundle，不要用 .gitignore 的 `!` 负规则放行。
        """
        import subprocess
        manifest = json.loads(MODULE.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
        repo_root = MODULE.DEFAULT_REPO_ROOT
        tracked = []
        for name, bundle in manifest["bundles"].items():
            for item in bundle.get("files", []):
                relative = f"{bundle['destination']}/{item['path']}"
                result = subprocess.run(
                    ["git", "-C", str(repo_root), "ls-files", "--error-unmatch", relative],
                    capture_output=True, text=True,
                )
                if result.returncode == 0:
                    tracked.append(f"{name}: {relative}")
        self.assertEqual([], tracked, "synchronized asset files must not be tracked by Git")
        for name in ("asr-shared-models-v1", "tts-harmony-icu-v1", "tts-onnxruntime-android-v1",
                     "tts-onnxruntime-harmony-v1", "tts-training-inputs-v1"):
            self.assertIn(name, manifest["bundles"])

    def test_manifest_defaults_to_cos_and_keeps_obs_legacy_for_restricted_bundles(self) -> None:
        """2026-11-16 起默认存储是腾讯云 COS；受限（SSE-KMS）bundle 留在具名的 obs-legacy 只读存储。"""
        manifest = json.loads(MODULE.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
        storages = MODULE.storages_from(manifest)
        self.assertEqual("tencent-cos", storages["default"].provider)
        self.assertEqual("ap-guangzhou", storages["default"].region)
        self.assertEqual(("COS_SecretId", "COS_SecretKey"),
                         (storages["default"].access_key_env, storages["default"].secret_key_env))
        self.assertEqual("huawei-obs", storages["obs-legacy"].provider)
        self.assertEqual("OBS_Endpoint", storages["obs-legacy"].endpoint_env)
        _, bundles = MODULE.load_registry(MODULE.DEFAULT_MANIFEST, MODULE.DEFAULT_REPO_ROOT)
        for name, bundle in bundles.items():
            if not bundle.owned:
                continue
            expected = "obs-legacy" if bundle.definition.get("encryption") == "sse-kms" else "default"
            self.assertEqual(expected, bundle.storage.name, name)
        # 新外置的五个 bundle 全部在默认（COS）存储上。
        for name in ("asr-shared-models-v1", "tts-harmony-icu-v1", "tts-onnxruntime-android-v1",
                     "tts-onnxruntime-harmony-v1", "tts-training-inputs-v1"):
            self.assertEqual("tencent-cos", bundles[name].storage.provider)

    def test_storage_parsing_rejects_incomplete_or_unknown_providers(self) -> None:
        base = {"bucket": "b", "access_key_env": "A", "secret_key_env": "S", "prefix": "p"}
        with self.assertRaises(MODULE.AssetError):
            MODULE.storage_from({"storage": {**base, "provider": "aws-s3"}})
        with self.assertRaises(MODULE.AssetError):
            MODULE.storage_from({"storage": {**base, "provider": "tencent-cos"}})  # no region
        with self.assertRaises(MODULE.AssetError):
            MODULE.storage_from({"storage": base})  # obs without endpoint_env
        legacy = MODULE.storage_from({"storage": {**base, "endpoint_env": "E"}})
        self.assertEqual("huawei-obs", legacy.provider)
        with self.assertRaises(MODULE.AssetError):
            MODULE.storages_from({"storage": {**base, "endpoint_env": "E"}, "storages": {"default": base}})

    def test_cos_identity_normalizes_headers_like_obs(self) -> None:
        size, sha, enc = MODULE.cos_identity_from_headers(
            {"content-length": "42", "x-cos-meta-sha256": "ab" * 32, "x-cos-server-side-encryption": "cos/kms"})
        self.assertEqual((42, "ab" * 32, "kms"), (size, sha, enc))
        size, sha, enc = MODULE.cos_identity_from_headers({"content-length": "7"})
        self.assertEqual((7, None, None), (size, sha, enc))
        with self.assertRaises(MODULE.AssetError):
            MODULE.cos_identity_from_headers({"etag": "x"})

    def test_mirror_refuses_restricted_bundles_and_same_storage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self.restricted_bundle(root)
            with self.assertRaises(MODULE.AssetError):
                MODULE.mirror_bundle(bundle, MODULE.Storage("other", "E", "A", "S", "p", name="src"))
            definition = dict(bundle.definition)
            definition.pop("encryption", None)
            plain = MODULE.Bundle("plain", definition, bundle.storage, root, True)
            self.assertEqual("same-storage", MODULE.mirror_bundle(plain, plain.storage))

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
