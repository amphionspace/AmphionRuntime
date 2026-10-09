from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

from asr.tools.tests.test_verify_community_encoder_mindir import MindirFixture


SCRIPT = Path(__file__).with_name("harmony_build_identity.py")
SPEC = importlib.util.spec_from_file_location("harmony_build_identity", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SoleHarTest(unittest.TestCase):
    def test_requires_exactly_one_har(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(MODULE.IdentityFailure, "expected one HAR"):
                MODULE.sole_har(root)
            (root / "one.har").write_bytes(b"one")
            self.assertEqual(root / "one.har", MODULE.sole_har(root))
            (root / "two.har").write_bytes(b"two")
            with self.assertRaisesRegex(MODULE.IdentityFailure, "found 2"):
                MODULE.sole_har(root)

    def test_zh_en_identity_still_binds_police_har_used_by_selfcontained_delivery(self) -> None:
        self.assertIn("amphion_police.har", MODULE.artifact_dirs(zh_en_only=True))

    def test_source_identity_binds_shared_cross_platform_models(self) -> None:
        self.assertIn("shared/models/asr", MODULE.TRACKED_BUILD_INPUTS)

    def test_tracked_path_fingerprint_changes_when_file_content_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.txt"
            path.write_text("before\n", encoding="utf-8")
            before = hashlib.sha256()
            MODULE.add_path(before, "input.txt", path)
            path.write_text("after\n", encoding="utf-8")
            after = hashlib.sha256()
            MODULE.add_path(after, "input.txt", path)
            self.assertNotEqual(before.hexdigest(), after.hexdigest())

    def test_runtime_recipe_and_patch_changes_invalidate_source_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            inputs = [
                "asr/tools/build_harmony_onnxruntime.py",
                "asr/tools/harmony_onnxruntime_flags.cmake",
                "third_party/patches/onnxruntime-amphion/worker.patch",
            ]
            for relative in inputs + ["notes.md"]:
                path = repo / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("original\n")
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            run = MODULE.run
            with mock.patch.object(MODULE, "REPO_ROOT", repo), mock.patch.object(
                MODULE, "run", side_effect=lambda command: run(command, cwd=repo)
            ), mock.patch.object(MODULE, "sherpa_source_fingerprint", return_value="unchanged"):
                before = MODULE.source_fingerprint()
                for relative in inputs:
                    with self.subTest(input=relative):
                        path = repo / relative
                        path.write_text("changed\n")
                        self.assertNotEqual(before, MODULE.source_fingerprint())
                        path.write_text("original\n")
                (repo / "notes.md").write_text("documentation only\n")
                self.assertEqual(before, MODULE.source_fingerprint())

    def test_sherpa_fingerprint_is_stable_before_and_after_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
            )
            source = repo / "source.cc"
            source.write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "source.cc"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
            subprocess.run(["git", "tag", "v1.13.1"], cwd=repo, check=True)
            source.write_text("patched\n", encoding="utf-8")

            before_commit = MODULE.sherpa_source_fingerprint(repo)
            subprocess.run(["git", "add", "source.cc"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "patch"], cwd=repo, check=True)

            self.assertEqual(before_commit, MODULE.sherpa_source_fingerprint(repo))

    def test_untracked_converter_content_invalidates_source_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            converter = repo / "asr/tools/convert_community_encoder.py"
            converter.parent.mkdir(parents=True)
            converter.write_text("original conversion recipe\n")
            run = MODULE.run
            with mock.patch.object(MODULE, "REPO_ROOT", repo), mock.patch.object(
                MODULE, "run", side_effect=lambda command: run(command, cwd=repo)
            ), mock.patch.object(MODULE, "sherpa_source_fingerprint", return_value="unchanged"):
                before = MODULE.source_fingerprint()
                converter.write_text("changed conversion recipe\n")
                self.assertNotEqual(before, MODULE.source_fingerprint())

    def test_ignored_model_and_provenance_content_invalidate_source_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            (repo / ".gitignore").write_text("*.ms\n*.ms.provenance.json\n*.onnx\n")
            shared = repo / "shared/models/asr/dingqiao"
            shared.mkdir(parents=True)
            names = ["community-wespeaker-encoder.fp32.onnx", "community-wespeaker-encoder.fp16.ms",
                     "community-wespeaker-encoder.fp16.ms.provenance.json"]
            for name in names:
                (shared / name).write_bytes(b"original")
            run = MODULE.run
            with mock.patch.object(MODULE, "REPO_ROOT", repo), mock.patch.object(
                MODULE, "run", side_effect=lambda command: run(command, cwd=repo)
            ), mock.patch.object(MODULE, "sherpa_source_fingerprint", return_value="unchanged"):
                before = MODULE.source_fingerprint()
                for name in names:
                    with self.subTest(input=name):
                        (shared / name).write_bytes(b"changed")
                        self.assertNotEqual(before, MODULE.source_fingerprint())
                        (shared / name).write_bytes(b"original")


class VerifyIdentityTest(unittest.TestCase):
    def test_rejects_stale_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            path.write_text(
                json.dumps({"git_commit": "old", "build_mode": "debug"}),
                encoding="utf-8",
            )
            with mock.patch.object(
                MODULE,
                "current_identity",
                return_value={"git_commit": "new", "build_mode": "debug"},
            ):
                with self.assertRaisesRegex(MODULE.IdentityFailure, "stale"):
                    MODULE.verify_identity(path)

    def test_accepts_created_at_as_non_identity_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            with mock.patch.object(
                MODULE,
                "current_identity",
                return_value={"git_commit": "same", "build_mode": "debug"},
            ):
                payload = {"git_commit": "same", "build_mode": "debug", "created_at": "timestamp"}
                path.write_text(json.dumps(payload), encoding="utf-8")
                MODULE.verify_identity(path)

    def test_rejects_identity_from_another_build_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            path.write_text(
                json.dumps({"git_commit": "same", "build_mode": "debug"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(MODULE.IdentityFailure, "build mode mismatch"):
                MODULE.verify_identity(path, "diagnostics")


class OptionalModelIdentityTest(unittest.TestCase):
    def test_mindir_is_in_the_optional_model_inventory(self) -> None:
        self.assertEqual(
            "resources/rawfile/amphion-dingqiao/community-wespeaker-encoder.fp16.ms",
            MODULE.OPTIONAL_HAP_MODELS.get("community_speaker_encoder_mindir"),
        )

    def test_rejects_corrupt_mindir_instead_of_omitting_it_from_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            shared = repo / "shared/models/asr/dingqiao"
            shared.mkdir(parents=True)
            (shared / "community-wespeaker-encoder.fp16.ms").write_bytes(b"expected-model")
            hap = repo / "test.hap"
            with zipfile.ZipFile(hap, "w") as archive:
                archive.writestr(
                    "resources/rawfile/amphion-dingqiao/community-wespeaker-encoder.fp16.ms",
                    b"damaged-model",
                )
            with mock.patch.object(MODULE, "REPO_ROOT", repo), mock.patch.object(MODULE, "HAP", hap):
                with self.assertRaises(MODULE.IdentityFailure):
                    MODULE.optional_hap_models()

    def test_records_all_community_assets_from_hap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hap = Path(directory) / 'test.hap'
            names = ['community_speaker_encoder', 'community_speaker_pooling',
                     'community_feature_transform', 'community_plda']
            with zipfile.ZipFile(hap, 'w') as archive:
                for name in names:
                    archive.writestr(MODULE.OPTIONAL_HAP_MODELS[name], name.encode())
            with mock.patch.object(MODULE, 'HAP', hap), mock.patch.object(MODULE, "REPO_ROOT", Path(directory)):
                models = MODULE.optional_hap_models()
            import hashlib
            for name in names:
                self.assertEqual(hashlib.sha256(name.encode()).hexdigest(), models[name]['sha256'])
                self.assertEqual(len(name), models[name]['size_bytes'])

    def test_records_separator_bytes_from_hap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hap = Path(directory) / "test.hap"
            member = MODULE.OPTIONAL_HAP_MODELS["target_speaker_separator"]
            with zipfile.ZipFile(hap, "w") as archive:
                archive.writestr(member, b"separator-model")
            with mock.patch.object(MODULE, "HAP", hap), mock.patch.object(MODULE, "REPO_ROOT", Path(directory)):
                models = MODULE.optional_hap_models()
            self.assertEqual(15, models["target_speaker_separator"]["size_bytes"])
            self.assertEqual(member, models["target_speaker_separator"]["hap_path"])
            self.assertEqual(
                "92cf99547b8f6e437b108d8ac0abd3bb47844e446c8ead8fba17a2ce917534a2",
                models["target_speaker_separator"]["sha256"],
            )


class MindirOptionalModelIdentityTest(MindirFixture):
    def setUp(self):
        super().setUp()
        self.sync_generated()
        self.hap = self.write_archive()
        self.har = self.write_archive("tar")

    def models(self):
        with mock.patch.object(MODULE, "REPO_ROOT", self.repo), mock.patch.object(MODULE, "HAP", self.hap):
            return MODULE.optional_hap_models(self.har)

    def test_records_verified_mindir_sources_provenance_and_actual_payload(self):
        model = self.models()["community_speaker_encoder_mindir"]
        self.assertEqual(self.record["output"]["sha256"], model["sha256"])
        self.assertEqual(self.record["output"]["sizeBytes"], model["size_bytes"])
        self.assertEqual(self.record["source"]["sha256"], model["source_sha256"])
        self.assertEqual(hashlib.sha256(self.provenance.read_bytes()).hexdigest(), model["provenance_sha256"])
        self.assertEqual(MODULE.OPTIONAL_HAP_MODELS["community_speaker_encoder_mindir"], model["hap_path"])

    def test_valid_provenance_does_not_hide_corrupted_hap_har_or_generated_bytes(self):
        for stage in ["hap", "har", "generated"]:
            with self.subTest(stage=stage):
                self.sync_generated()
                self.hap = self.write_archive()
                self.har = self.write_archive("tar")
                damaged = self.output.read_bytes()[:-1] + b"!"
                if stage == "hap":
                    self.hap = self.write_archive(entries=[(MODULE.community_mindir.HAP_MEMBER, damaged)])
                elif stage == "har":
                    self.har = self.write_archive("tar", [("package/src/main/" + MODULE.community_mindir.HAP_MEMBER, damaged)])
                else:
                    (self.generated / self.output.name).write_bytes(damaged)
                with self.assertRaisesRegex(MODULE.IdentityFailure, "SHA-256/bytes mismatch"):
                    self.models()

    def test_packaged_model_needs_sources_and_cannot_ship_provenance(self):
        self.provenance.unlink()
        with self.assertRaisesRegex(MODULE.IdentityFailure, "source/provenance"):
            self.models()
        self.write_provenance()
        self.hap = self.write_archive(entries=[(MODULE.community_mindir.HAP_MEMBER, self.output.read_bytes()),
                                               ("resources/rawfile/" + self.provenance.name, self.provenance.read_bytes())])
        with self.assertRaisesRegex(MODULE.IdentityFailure, "must not be packaged"):
            self.models()


if __name__ == "__main__":
    unittest.main()
