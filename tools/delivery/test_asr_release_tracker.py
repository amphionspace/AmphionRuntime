import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("asr_release_tracker.py")
SPEC = importlib.util.spec_from_file_location("asr_release_tracker", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AsrReleaseTrackerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)
        self.git("init", "-q")
        self.git("config", "user.email", "release-test@example.com")
        self.git("config", "user.name", "Release Test")
        android = self.repo / "asr" / "android"
        android.mkdir(parents=True)
        (android / "sdk.txt").write_text("base\n", encoding="utf-8")
        self.git("add", "asr/android/sdk.txt")
        self.git("commit", "-q", "-m", "chore(android): release version 0.3.2")
        self.android_base = self.git("rev-parse", "HEAD")
        self.history_path = self.repo / "delivery" / "asr-sdk-release-history.json"
        self.history_path.parent.mkdir()
        self.history_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "deliveries": [
                        {
                            "platform": "android",
                            "version": "0.3.2",
                            "source_commit": self.android_base,
                            "delivered_at": "2026-07-24",
                            "artifact": "android-0.3.2.zip",
                            "provenance_sha256": "a" * 64,
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.git("add", "delivery/asr-sdk-release-history.json")
        self.git("commit", "-q", "-m", "chore(delivery): record ASR SDK delivery")
        (android / "sdk.txt").write_text("fixed\n", encoding="utf-8")
        self.git("add", "asr/android/sdk.txt")
        self.git("commit", "-q", "-m", "fix(android): preserve trailing words")
        self.current_commit = self.git("rev-parse", "HEAD")
        self.primary_branch = self.git("branch", "--show-current")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def git(self, *args: str) -> str:
        return subprocess.run(
            ("git", *args),
            cwd=self.repo,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()

    def test_renders_changes_since_previous_platform_delivery(self) -> None:
        rendered = MODULE.render_changelog(
            repo=self.repo,
            history_path=self.history_path,
            platform="android",
            version="0.3.3",
            source_commit=self.current_commit,
        )

        self.assertIn("## Android ASR SDK 0.3.3", rendered)
        self.assertIn(self.current_commit, rendered)
        self.assertIn(f"0.3.2 (`{self.android_base}`)", rendered)
        self.assertIn("fix(android): preserve trailing words", rendered)
        self.assertNotIn("record ASR SDK delivery", rendered)

    def test_excludes_commits_that_only_touch_the_other_platform(self) -> None:
        harmony = self.repo / "asr" / "harmony"
        harmony.mkdir(parents=True)
        (harmony / "sdk.txt").write_text("harmony only\n", encoding="utf-8")
        self.git("add", "asr/harmony/sdk.txt")
        self.git("commit", "-q", "-m", "fix(harmony): platform-only change")
        latest = self.git("rev-parse", "HEAD")

        rendered = MODULE.render_changelog(
            repo=self.repo,
            history_path=self.history_path,
            platform="android",
            version="0.3.3",
            source_commit=latest,
        )

        self.assertIn("fix(android): preserve trailing words", rendered)
        self.assertNotIn("platform-only change", rendered)

    def test_rejects_previous_delivery_commit_from_another_history(self) -> None:
        self.git("checkout", "--orphan", "side")
        self.git("rm", "-q", "-rf", ".")
        (self.repo / "side.txt").write_text("side\n", encoding="utf-8")
        self.git("add", "side.txt")
        self.git("commit", "-q", "-m", "fix(android): unrelated line")
        side_commit = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", self.primary_branch)
        payload = json.loads(self.history_path.read_text(encoding="utf-8"))
        payload["deliveries"][0]["source_commit"] = side_commit
        self.history_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(MODULE.ReleaseTrackerError, "not an ancestor"):
            MODULE.render_changelog(
                repo=self.repo,
                history_path=self.history_path,
                platform="android",
                version="0.3.3",
                source_commit=self.current_commit,
            )

    def test_records_version_from_android_provenance_and_rejects_duplicate(self) -> None:
        provenance = self.repo / "VERSION.txt"
        provenance.write_text(
            "delivery_version=0.3.3\n"
            f"git_commit_full={self.current_commit}\n",
            encoding="utf-8",
        )

        entry = MODULE.record_delivery(
            repo=self.repo,
            history_path=self.history_path,
            platform="android",
            version="0.3.3",
            source_commit=self.current_commit,
            delivered_at="2026-07-30",
            artifact="amphion-dingqiao-v0.3.3-customer-20260730.zip",
            provenance_path=provenance,
        )

        self.assertEqual("android", entry["platform"])
        self.assertEqual(self.current_commit, entry["source_commit"])
        self.assertEqual(2, len(MODULE.load_history(self.history_path)["deliveries"]))
        with self.assertRaisesRegex(MODULE.ReleaseTrackerError, "already recorded"):
            MODULE.record_delivery(
                repo=self.repo,
                history_path=self.history_path,
                platform="android",
                version="0.3.3",
                source_commit=self.current_commit,
                delivered_at="2026-07-30",
                artifact="duplicate.zip",
                provenance_path=provenance,
            )

    def test_rejects_harmony_provenance_commit_mismatch(self) -> None:
        provenance = self.repo / "BUILD_PROVENANCE.json"
        provenance.write_text(
            json.dumps(
                {
                    "delivery_version": "0.2.9",
                    "source": {"commit": self.android_base},
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(MODULE.ReleaseTrackerError, "provenance commit"):
            MODULE.record_delivery(
                repo=self.repo,
                history_path=self.history_path,
                platform="harmony",
                version="0.2.9",
                source_commit=self.current_commit,
                delivered_at="2026-07-30",
                artifact="amphion-harmony-asr-sdk-0.2.9",
                provenance_path=provenance,
            )


if __name__ == "__main__":
    unittest.main()
