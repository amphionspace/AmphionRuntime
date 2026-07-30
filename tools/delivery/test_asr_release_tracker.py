import fcntl
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor, TimeoutError
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
                    "schema_version": 2,
                    "deliveries": [
                        {
                            "platform": "android",
                            "version": "0.3.2",
                            "source_commit": self.android_base,
                            "delivered_at": "2026-07-24",
                            "artifact": "android-0.3.2.zip",
                            "artifact_sha256": "b" * 64,
                            "artifact_size_bytes": 123,
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

    def artifact(self, platform: str, provenance: Path, name: str) -> Path:
        path = self.repo / name
        member = (
            "delivery/VERSION.txt"
            if platform == "android"
            else "delivery/docs/BUILD_PROVENANCE.json"
        )
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(member, provenance.read_bytes())
        return path

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

    def test_excludes_android_delivery_tools_from_harmony_changelog(self) -> None:
        android_delivery = self.repo / "asr" / "tools" / "delivery"
        android_delivery.mkdir(parents=True)
        (android_delivery / "pack_android.sh").write_text("android only\n", encoding="utf-8")
        self.git("add", "asr/tools/delivery/pack_android.sh")
        self.git("commit", "-q", "-m", "feat(android): package zh-en SDK")
        latest = self.git("rev-parse", "HEAD")

        rendered = MODULE.render_changelog(
            repo=self.repo,
            history_path=self.history_path,
            platform="harmony",
            version="0.2.9",
            source_commit=latest,
        )

        self.assertNotIn("package zh-en SDK", rendered)

    def test_includes_harmony_packaging_tools_in_harmony_changelog(self) -> None:
        harmony_tool = self.repo / "asr" / "tools" / "08_pack_harmony_assets.sh"
        harmony_tool.parent.mkdir(parents=True, exist_ok=True)
        harmony_tool.write_text("harmony assets\n", encoding="utf-8")
        self.git("add", "asr/tools/08_pack_harmony_assets.sh")
        self.git("commit", "-q", "-m", "fix(harmony): update model asset packer")
        latest = self.git("rev-parse", "HEAD")

        rendered = MODULE.render_changelog(
            repo=self.repo,
            history_path=self.history_path,
            platform="harmony",
            version="0.2.9",
            source_commit=latest,
        )

        self.assertIn("update model asset packer", rendered)

    def test_explicit_platform_scope_excludes_opposite_platform(self) -> None:
        harmony_tool = self.repo / "asr" / "tools" / "build_harmony_asset_manifest.py"
        harmony_tool.parent.mkdir(parents=True, exist_ok=True)
        harmony_tool.write_text("android asset support\n", encoding="utf-8")
        self.git("add", "asr/tools/build_harmony_asset_manifest.py")
        self.git("commit", "-q", "-m", "perf(android): accelerate model loading")
        latest = self.git("rev-parse", "HEAD")

        rendered = MODULE.render_changelog(
            repo=self.repo,
            history_path=self.history_path,
            platform="harmony",
            version="0.2.9",
            source_commit=latest,
        )

        self.assertNotIn("accelerate model loading", rendered)

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
        artifact = self.artifact(
            "android", provenance, "amphion-dingqiao-asr-sdk-v0.3.3-20260730.zip"
        )

        entry = MODULE.record_delivery(
            repo=self.repo,
            history_path=self.history_path,
            platform="android",
            version="0.3.3",
            source_commit=self.current_commit,
            delivered_at="2026-07-30",
            artifact_path=artifact,
        )

        self.assertEqual("android", entry["platform"])
        self.assertEqual(self.current_commit, entry["source_commit"])
        self.assertEqual(hashlib.sha256(artifact.read_bytes()).hexdigest(), entry["artifact_sha256"])
        self.assertEqual(artifact.stat().st_size, entry["artifact_size_bytes"])
        self.assertEqual(2, len(MODULE.load_history(self.history_path)["deliveries"]))
        with self.assertRaisesRegex(MODULE.ReleaseTrackerError, "already recorded"):
            MODULE.record_delivery(
                repo=self.repo,
                history_path=self.history_path,
                platform="android",
                version="0.3.3",
                source_commit=self.current_commit,
                delivered_at="2026-07-30",
                artifact_path=artifact,
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
        artifact = self.artifact("harmony", provenance, "amphion-harmony-asr-sdk-v0.2.9.zip")

        with self.assertRaisesRegex(MODULE.ReleaseTrackerError, "provenance commit"):
            MODULE.record_delivery(
                repo=self.repo,
                history_path=self.history_path,
                platform="harmony",
                version="0.2.9",
                source_commit=self.current_commit,
                delivered_at="2026-07-30",
                artifact_path=artifact,
            )

    def test_rejects_artifact_without_embedded_provenance(self) -> None:
        artifact = self.repo / "amphion-dingqiao-asr-sdk-v0.3.3.zip"
        with zipfile.ZipFile(artifact, "w") as archive:
            archive.writestr("delivery/README.txt", "missing provenance\n")

        with self.assertRaisesRegex(MODULE.ReleaseTrackerError, "exactly one VERSION.txt"):
            MODULE.record_delivery(
                repo=self.repo,
                history_path=self.history_path,
                platform="android",
                version="0.3.3",
                source_commit=self.current_commit,
                delivered_at="2026-07-30",
                artifact_path=artifact,
            )

    def test_record_waits_for_history_lock(self) -> None:
        provenance = self.repo / "VERSION.txt"
        provenance.write_text(
            "delivery_version=0.3.3\n"
            f"git_commit_full={self.current_commit}\n",
            encoding="utf-8",
        )
        artifact = self.artifact("android", provenance, "android-0.3.3.zip")
        lock_path = MODULE._history_lock_path(self.history_path)
        with lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    MODULE.record_delivery,
                    repo=self.repo,
                    history_path=self.history_path,
                    platform="android",
                    version="0.3.3",
                    source_commit=self.current_commit,
                    delivered_at="2026-07-30",
                    artifact_path=artifact,
                )
                with self.assertRaises(TimeoutError):
                    future.result(timeout=0.2)
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                self.assertEqual("0.3.3", future.result(timeout=2)["version"])

    def test_concurrent_platform_records_preserve_both_deliveries(self) -> None:
        android_provenance = self.repo / "VERSION.txt"
        android_provenance.write_text(
            "delivery_version=0.3.3\n"
            f"git_commit_full={self.current_commit}\n",
            encoding="utf-8",
        )
        harmony_provenance = self.repo / "BUILD_PROVENANCE.json"
        harmony_provenance.write_text(
            json.dumps(
                {
                    "delivery_version": "0.2.9",
                    "source": {"commit": self.current_commit},
                }
            ),
            encoding="utf-8",
        )
        android_artifact = self.artifact("android", android_provenance, "android-0.3.3.zip")
        harmony_artifact = self.artifact("harmony", harmony_provenance, "harmony-0.2.9.zip")
        calls = (
            {
                "platform": "android",
                "version": "0.3.3",
                "artifact_path": android_artifact,
            },
            {
                "platform": "harmony",
                "version": "0.2.9",
                "artifact_path": harmony_artifact,
            },
        )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    MODULE.record_delivery,
                    repo=self.repo,
                    history_path=self.history_path,
                    source_commit=self.current_commit,
                    delivered_at="2026-07-30",
                    **call,
                )
                for call in calls
            ]
            for future in futures:
                future.result(timeout=2)

        deliveries = MODULE.load_history(self.history_path)["deliveries"]
        self.assertEqual(
            {("android", "0.3.2"), ("android", "0.3.3"), ("harmony", "0.2.9")},
            {(entry["platform"], entry["version"]) for entry in deliveries},
        )


if __name__ == "__main__":
    unittest.main()
