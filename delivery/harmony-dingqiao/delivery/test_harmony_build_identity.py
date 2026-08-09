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


class VerifyIdentityTest(unittest.TestCase):
    def test_rejects_stale_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            path.write_text(json.dumps({"git_commit": "old"}), encoding="utf-8")
            with mock.patch.object(MODULE, "current_identity", return_value={"git_commit": "new"}):
                with self.assertRaisesRegex(MODULE.IdentityFailure, "stale"):
                    MODULE.verify_identity(path)

    def test_accepts_created_at_as_non_identity_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            path.write_text(
                json.dumps({"git_commit": "same", "created_at": "timestamp"}), encoding="utf-8"
            )
            with mock.patch.object(MODULE, "current_identity", return_value={"git_commit": "same"}):
                MODULE.verify_identity(path)


class OptionalModelIdentityTest(unittest.TestCase):
    def test_records_separator_bytes_from_hap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hap = Path(directory) / "test.hap"
            member = MODULE.OPTIONAL_HAP_MODELS["target_speaker_separator"]
            with zipfile.ZipFile(hap, "w") as archive:
                archive.writestr(member, b"separator-model")
            with mock.patch.object(MODULE, "HAP", hap):
                models = MODULE.optional_hap_models()
            self.assertEqual(15, models["target_speaker_separator"]["size_bytes"])
            self.assertEqual(member, models["target_speaker_separator"]["hap_path"])
            self.assertEqual(
                "92cf99547b8f6e437b108d8ac0abd3bb47844e446c8ead8fba17a2ce917534a2",
                models["target_speaker_separator"]["sha256"],
            )


if __name__ == "__main__":
    unittest.main()
