import fcntl
import hashlib
import importlib.util
import json
import os
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

    def test_release_versions_must_increase_per_platform(self) -> None:
        payload = json.loads(self.history_path.read_text(encoding="utf-8"))
        stale = dict(payload["deliveries"][0])
        stale["version"] = "0.3.1"
        payload["deliveries"].append(stale)
        self.history_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(MODULE.ReleaseTrackerError, "strictly increase"):
            MODULE.load_history(self.history_path)

    def test_verify_next_version_rejects_recorded_or_older_versions(self) -> None:
        MODULE.verify_next_version(
            history_path=self.history_path,
            platform="android",
            version="0.3.3",
        )
        for stale in ("0.3.2", "0.3.1"):
            with self.subTest(stale=stale):
                with self.assertRaisesRegex(MODULE.ReleaseTrackerError, "newer than 0.3.2"):
                    MODULE.verify_next_version(
                        history_path=self.history_path,
                        platform="android",
                        version=stale,
                    )

    def test_verify_current_version_requires_latest_record_and_ancestor(self) -> None:
        MODULE.verify_current_version(
            repo=self.repo,
            history_path=self.history_path,
            platform="android",
            version="0.3.2",
            source_commit=self.current_commit,
        )
        with self.assertRaisesRegex(MODULE.ReleaseTrackerError, "latest recorded.*0.3.2"):
            MODULE.verify_current_version(
                repo=self.repo,
                history_path=self.history_path,
                platform="android",
                version="0.3.3",
                source_commit=self.current_commit,
            )

    def test_packaging_accepts_new_or_exact_recorded_source(self) -> None:
        self.assertEqual(
            MODULE.verify_packaging_version(
                repo=self.repo,
                history_path=self.history_path,
                platform="android",
                version="0.3.3",
                source_commit=self.current_commit,
            ),
            "next",
        )
        payload = json.loads(self.history_path.read_text(encoding="utf-8"))
        payload["deliveries"].append(
            {
                "platform": "android",
                "version": "0.3.3",
                "source_commit": self.current_commit,
                "delivered_at": "2026-07-25",
                "artifact": "android-0.3.3.zip",
                "artifact_sha256": "c" * 64,
                "artifact_size_bytes": 456,
                "provenance_sha256": "d" * 64,
            }
        )
        self.history_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

        self.assertEqual(
            MODULE.verify_packaging_version(
                repo=self.repo,
                history_path=self.history_path,
                platform="android",
                version="0.3.3",
                source_commit=self.current_commit,
            ),
            "current",
        )
        with self.assertRaisesRegex(MODULE.ReleaseTrackerError, "exact source"):
            MODULE.verify_packaging_version(
                repo=self.repo,
                history_path=self.history_path,
                platform="android",
                version="0.3.3",
                source_commit=self.android_base,
            )

        rendered = MODULE.render_changelog(
            repo=self.repo,
            history_path=self.history_path,
            platform="android",
            version="0.3.3",
            source_commit=self.current_commit,
        )
        self.assertIn(f"0.3.2 (`{self.android_base}`)", rendered)
        self.assertNotIn("上一交付：0.3.3", rendered)

    def test_formal_packaging_requires_exact_recorded_version_and_source(self) -> None:
        with self.assertRaisesRegex(
            MODULE.ReleaseTrackerError, "PREVIEW / NON-CANONICAL"
        ):
            MODULE.verify_recorded_packaging_version(
                repo=self.repo,
                history_path=self.history_path,
                platform="android",
                version="0.3.3",
                source_commit=self.current_commit,
            )

        payload = json.loads(self.history_path.read_text(encoding="utf-8"))
        payload["deliveries"].append(
            {
                "platform": "android",
                "version": "0.3.3",
                "source_commit": self.current_commit,
                "delivered_at": "2026-07-25",
                "artifact": "android-0.3.3.zip",
                "artifact_sha256": "c" * 64,
                "artifact_size_bytes": 456,
                "provenance_sha256": "d" * 64,
            }
        )
        self.history_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

        MODULE.verify_recorded_packaging_version(
            repo=self.repo,
            history_path=self.history_path,
            platform="android",
            version="0.3.3",
            source_commit=self.current_commit,
        )

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

    def test_changelog_uses_recorded_integration_commit_after_squash_merge(self) -> None:
        self.git("checkout", "--orphan", "release-source")
        self.git("rm", "-q", "-rf", ".")
        (self.repo / "release.txt").write_text("release source\n", encoding="utf-8")
        self.git("add", "release.txt")
        self.git("commit", "-q", "-m", "feat(android): release branch source")
        release_source = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", self.primary_branch)

        payload = json.loads(self.history_path.read_text(encoding="utf-8"))
        payload["deliveries"][0]["source_commit"] = release_source
        payload["deliveries"][0]["integration_commit"] = self.android_base
        self.history_path.write_text(json.dumps(payload), encoding="utf-8")

        rendered = MODULE.render_changelog(
            repo=self.repo,
            history_path=self.history_path,
            platform="android",
            version="0.3.3",
            source_commit=self.current_commit,
        )

        self.assertIn(f"0.3.2 (`{release_source}`)", rendered)
        self.assertIn("fix(android): preserve trailing words", rendered)

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

    def test_record_delivery_return_type_allows_numeric_artifact_size(self) -> None:
        self.assertEqual("Dict[str, Any]", MODULE.record_delivery.__annotations__["return"])

    def test_attaches_and_verifies_immutable_release_evidence(self) -> None:
        report = self.repo / "delivery" / "evidence" / "android-0.3.2" / "report.json"
        report.parent.mkdir(parents=True)
        android = report.parent / "android-tests.json"
        android.write_text("{}\n", encoding="utf-8")
        gradle = report.parent / "android-test-results" / "sdk" / "debug" / "TEST.xml"
        gradle.parent.mkdir(parents=True)
        gradle.write_text(
            '<testsuite tests="1" failures="0" errors="0" skipped="0" '
            'hostname="redacted"/>\n',
            encoding="utf-8",
        )
        report.write_text(
            json.dumps(
                {
                    "overall_status": "PASS",
                    "release_version": "0.3.2",
                    "source_commit": self.android_base,
                    "release_artifact": {
                        "name": "android-0.3.2.zip",
                        "sha256": "b" * 64,
                        "size_bytes": 123,
                        "provenance_sha256": "a" * 64,
                    },
                    "android_tests_artifact": {
                        "path": "android-tests.json",
                        "sha256": hashlib.sha256(android.read_bytes()).hexdigest(),
                        "size_bytes": android.stat().st_size,
                    },
                    "android_test_results": [
                        {
                            "path": gradle.relative_to(report.parent).as_posix(),
                            "sha256": hashlib.sha256(gradle.read_bytes()).hexdigest(),
                            "size_bytes": gradle.stat().st_size,
                        }
                    ],
                    "modes": [],
                    "diagnostics": [],
                }
            )
            + "\n",
            encoding="utf-8",
        )

        entry = MODULE.attach_evidence(
            repo=self.repo,
            history_path=self.history_path,
            platform="android",
            version="0.3.2",
            report_path=report,
        )

        self.assertEqual(
            "delivery/evidence/android-0.3.2/report.json", entry["evidence_report"]
        )
        self.assertEqual(
            hashlib.sha256(report.read_bytes()).hexdigest(), entry["evidence_sha256"]
        )
        MODULE.verify_history_evidence(repo=self.repo, history_path=self.history_path)
        with self.assertRaisesRegex(MODULE.ReleaseTrackerError, "already has evidence"):
            MODULE.attach_evidence(
                repo=self.repo,
                history_path=self.history_path,
                platform="android",
                version="0.3.2",
                report_path=report,
            )

        report.write_text('{"overall_status":"FAIL"}\n', encoding="utf-8")
        with self.assertRaisesRegex(MODULE.ReleaseTrackerError, "digest mismatch"):
            MODULE.verify_history_evidence(repo=self.repo, history_path=self.history_path)

    def test_record_with_evidence_is_atomic_when_evidence_is_invalid(self) -> None:
        provenance = self.repo / "VERSION.txt"
        provenance.write_text(
            f"delivery_version=0.3.4\ngit_commit_full={self.current_commit}\n",
            encoding="utf-8",
        )
        artifact = self.artifact("android", provenance, "android-0.3.4.zip")
        report = self.repo / "delivery/evidence/android-0.3.4/report.json"
        report.parent.mkdir(parents=True)
        report.write_text('{"overall_status":"FAIL"}\n', encoding="utf-8")
        before = self.history_path.read_bytes()

        with self.assertRaises(MODULE.ReleaseTrackerError):
            MODULE.record_delivery_with_evidence(
                repo=self.repo,
                history_path=self.history_path,
                platform="android",
                version="0.3.4",
                source_commit=self.current_commit,
                delivered_at="2026-08-13",
                artifact_path=artifact,
                report_path=report,
            )

        self.assertEqual(before, self.history_path.read_bytes())

    def test_rejects_semantically_mismatched_or_tampered_evidence(self) -> None:
        report = self.repo / "delivery" / "evidence" / "android-0.3.2" / "report.json"
        report.parent.mkdir(parents=True)
        android = report.parent / "android-tests.json"
        android.write_text("{}\n", encoding="utf-8")
        gradle = report.parent / "android-test-results" / "sdk" / "debug" / "TEST.xml"
        gradle.parent.mkdir(parents=True)
        gradle.write_text(
            '<testsuite tests="1" failures="0" errors="0" skipped="0" '
            'hostname="redacted"/>\n',
            encoding="utf-8",
        )
        payload = {
            "overall_status": "PASS",
            "release_version": "0.3.2",
            "source_commit": self.android_base,
            "release_artifact": {
                "name": "wrong.zip",
                "sha256": "b" * 64,
                "size_bytes": 123,
                "provenance_sha256": "a" * 64,
            },
            "android_tests_artifact": {
                "path": "android-tests.json",
                "sha256": hashlib.sha256(android.read_bytes()).hexdigest(),
                "size_bytes": android.stat().st_size,
            },
            "android_test_results": [
                {
                    "path": gradle.relative_to(report.parent).as_posix(),
                    "sha256": hashlib.sha256(gradle.read_bytes()).hexdigest(),
                    "size_bytes": gradle.stat().st_size,
                }
            ],
            "modes": [],
            "diagnostics": [],
        }
        report.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(MODULE.ReleaseTrackerError, "artifact name"):
            MODULE.attach_evidence(
                repo=self.repo,
                history_path=self.history_path,
                platform="android",
                version="0.3.2",
                report_path=report,
            )

        payload["release_artifact"]["name"] = "android-0.3.2.zip"
        payload["extra"] = "allowed report field"
        report.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        (report.parent / "unmanifested.txt").write_text("hidden\n", encoding="utf-8")
        with self.assertRaisesRegex(MODULE.ReleaseTrackerError, "unmanifested file"):
            MODULE.attach_evidence(
                repo=self.repo,
                history_path=self.history_path,
                platform="android",
                version="0.3.2",
                report_path=report,
            )

    def test_atomic_history_update_preserves_file_mode(self) -> None:
        os.chmod(self.history_path, 0o644)
        history = MODULE.load_history(self.history_path)
        MODULE._write_history_atomic(self.history_path, history)
        self.assertEqual(0o644, self.history_path.stat().st_mode & 0o777)

    def test_harmony_evidence_cannot_omit_the_release_matrix(self) -> None:
        entry = dict(MODULE.load_history(self.history_path)["deliveries"][0])
        entry["platform"] = "harmony"
        report = {
            "overall_status": "PASS",
            "release_version": entry["version"],
            "source_commit": entry["source_commit"],
            "release_artifact": {
                "name": entry["artifact"],
                "sha256": entry["artifact_sha256"],
                "size_bytes": entry["artifact_size_bytes"],
                "provenance_sha256": entry["provenance_sha256"],
            },
            "schema_version": 1,
            "required_modes": [],
            "modes": [],
            "long_run": {"mode": "voiceprint-fallback", "duration_seconds": 82},
        }
        with self.assertRaisesRegex(MODULE.ReleaseTrackerError, "required_modes"):
            MODULE._validate_evidence_report(entry, report)

    def test_harmony_evidence_cannot_omit_finish_compat_child_runs(self) -> None:
        report_path = self.repo / "delivery" / "evidence" / "harmony" / "report.json"
        report_path.parent.mkdir(parents=True)
        android = report_path.parent / "android-tests.json"
        android.write_text("{}\n", encoding="utf-8")
        report = {
            "release_version": "0.3.6",
            "required_modes": list(MODULE.HARMONY_RELEASE_MODES),
            "android_tests_artifact": {
                "path": "android-tests.json",
                "sha256": hashlib.sha256(android.read_bytes()).hexdigest(),
                "size_bytes": android.stat().st_size,
            },
            "finish_compat_runs": [],
        }

        with self.assertRaisesRegex(MODULE.ReleaseTrackerError, "modes are incomplete"):
            MODULE._validate_evidence_files(report_path, report)

    def test_rejects_malformed_archived_android_xml(self) -> None:
        xml = self.repo / "bad.xml"
        xml.write_text('<testsuite hostname="redacted"><broken>\n', encoding="utf-8")
        with self.assertRaisesRegex(MODULE.ReleaseTrackerError, "invalid Android test XML"):
            MODULE._validate_android_test_xml(xml)

    def test_rejects_partial_or_unsafe_evidence_fields(self) -> None:
        payload = json.loads(self.history_path.read_text(encoding="utf-8"))
        payload["deliveries"][0]["evidence_report"] = "../outside/report.json"
        self.history_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(MODULE.ReleaseTrackerError, "evidence fields"):
            MODULE.load_history(self.history_path)

        payload["deliveries"][0]["evidence_sha256"] = "f" * 64
        self.history_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(MODULE.ReleaseTrackerError, "repo-relative"):
            MODULE.load_history(self.history_path)

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
