from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name("archive_release_gate_evidence.py")
SPEC = importlib.util.spec_from_file_location("archive_release_gate_evidence", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ArchiveReleaseGateEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.raw = self.root / "raw"
        self.output = self.root / "evidence"
        self.device = "SERIAL-PRIVATE-123"
        self.commit_timestamp = mock.patch.object(
            MODULE, "commit_timestamp_utc", return_value=datetime(2026, 8, 7, 9, 58)
        )
        self.commit_timestamp.start()
        self.android_summary = self.root / "android-tests.json"
        self.finish_summary = self.root / "finish-compat-report.json"
        self.finish_raw = self.root / "finish-raw"
        finish_modes = []
        finish_reports = {}
        for mode in MODULE.REQUIRED_FINISH_COMPAT_MODES:
            run_id = f"20260807-095800-{mode}-pass"
            run = self.finish_raw / run_id
            (run / "payload").mkdir(parents=True)
            report = {
                "run_id": run_id,
                "mode": mode,
                "overall_status": "PASS",
                "device": self.device,
                "build_identity": {
                    "git_commit": "a" * 40,
                    "source_fingerprint_sha256": "b" * 64,
                    "artifacts": {
                        "amphion_asr_demo.hap": {"sha256": "c" * 64},
                        "amphion_asr.har": {"sha256": "1" * 64},
                        "amphion_police.har": {"sha256": "2" * 64},
                        "amphion_dingqiao.har": {"sha256": "e" * 64},
                        "sherpa_onnx.har": {"sha256": "3" * 64},
                    },
                },
            }
            (run / "report.json").write_text(json.dumps(report), encoding="utf-8")
            (run / "result.txt").write_text("PASS\n", encoding="utf-8")
            (run / "memory.csv").write_text("elapsed_seconds,pid\n0,1\n", encoding="utf-8")
            (run / "hilog.txt").write_text("ASR_STRESS|PASS\n", encoding="utf-8")
            (run / "inventory.json").write_text("{}\n", encoding="utf-8")
            (run / "payload" / "corpus.json").write_text("{}\n", encoding="utf-8")
            (run / "payload" / "manifest.txt").write_text("fixture\n", encoding="utf-8")
            finish_modes.append({"mode": mode, "run_id": run_id, "status": "PASS"})
            finish_reports[mode] = f"../finish-raw/{run_id}/report.json"
        self.finish_summary.write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "source_commit": "a" * 40,
                    "modes": finish_modes,
                    "reports": finish_reports,
                }
            ),
            encoding="utf-8",
        )
        self.build_identity = self.root / "build-identity.json"
        self.android_results = self.root / "android-results"
        for key, relative in MODULE.ANDROID_RESULT_DIRECTORIES.items():
            result = self.android_results / relative / "TEST-fixture.xml"
            result.parent.mkdir(parents=True, exist_ok=True)
            result.write_text(
                f'<testsuite name="{key[0]}-{key[1]}" tests="{MODULE.REQUIRED_ANDROID_SUITES[key]}" '
                'failures="0" errors="0" skipped="0" timestamp="2026-08-09T10:27:18" '
                'hostname="private.local"></testsuite>\n',
                encoding="utf-8",
            )
        self.android_summary.write_text(
            json.dumps(
                {
                    "overall_status": "PASS",
                    "source_commit": "a" * 40,
                    "rerun_tasks": True,
                    "sherpa_submodule_commit": "f" * 40,
                    "suites": [
                        {
                            "module": module,
                            "variant": variant,
                            "tests": tests,
                            "failures": 0,
                            "errors": 0,
                            "skipped": 0,
                        }
                        for (module, variant), tests in MODULE.REQUIRED_ANDROID_SUITES.items()
                    ],
                    "total_tests": sum(MODULE.REQUIRED_ANDROID_SUITES.values()),
                    "total_failures": 0,
                    "total_errors": 0,
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.commit_timestamp.stop()
        self.temporary.cleanup()

    def make_run(self, run_id: str, mode: str, status: str) -> Path:
        run = self.raw / run_id
        (run / "payload" / "audio").mkdir(parents=True)
        report = {
            "run_id": run_id,
            "mode": mode,
            "overall_status": status,
            "device": self.device,
            "configuration": {"cycles": 2},
            "application": {"completed": "2" if status == "PASS" else "1"},
            "memory": {"status": "PASS"},
            "build_identity": {
                "git_commit": "a" * 40,
                "source_fingerprint_sha256": "b" * 64,
                "artifacts": {
                    "amphion_asr_demo.hap": {"sha256": "c" * 64},
                    "amphion_asr.har": {"sha256": "1" * 64},
                    "amphion_police.har": {"sha256": "2" * 64},
                    "amphion_dingqiao.har": {"sha256": "e" * 64},
                    "sherpa_onnx.har": {"sha256": "3" * 64},
                },
            },
        }
        (run / "report.json").write_text(json.dumps(report), encoding="utf-8")
        self.build_identity.write_text(
            json.dumps(report["build_identity"]), encoding="utf-8"
        )
        (run / "result.txt").write_text(
            f"device={self.device} path=/Users/private/testdata/input.wav\n",
            encoding="utf-8",
        )
        (run / "memory.csv").write_text(
            "elapsed_seconds,pid\n0,1\n61,1\n", encoding="utf-8"
        )
        (run / "hilog.txt").write_text(
            f"serial={self.device} source=/Users/private/work/repo\n",
            encoding="utf-8",
        )
        (run / "inventory.json").write_text("{}\n", encoding="utf-8")
        (run / "payload" / "corpus.json").write_text(
            json.dumps([{"source": "/Users/private/testdata/input.wav"}]),
            encoding="utf-8",
        )
        (run / "payload" / "manifest.txt").write_text("fixture\n", encoding="utf-8")
        (run / "payload" / "audio" / "000000.pcm").write_bytes(b"private pcm")
        return run

    def test_archives_latest_pass_and_preserves_failed_diagnostic(self) -> None:
        failed = self.make_run("20260807-100000-vad-begin-failed", "vad-begin", "FAIL")
        passed = self.make_run("20260807-100100-vad-begin-passed", "vad-begin", "PASS")

        with mock.patch.object(MODULE, "REQUIRED_RELEASE_MODES", ("vad-begin",)):
            summary = MODULE.archive_evidence(
                raw_root=self.raw,
                output=self.output,
                release_version="0.3.1",
                source_commit="a" * 40,
                artifact_sha256="d" * 64,
                har_sha256="e" * 64,
                diagnostic_notes={failed.name: "test precondition failed"},
                android_summary=self.android_summary,
                android_results_root=self.android_results,
                finish_compat_raw_root=self.finish_raw,
            )

        self.assertEqual("PASS", summary["overall_status"])
        self.assertEqual(passed.name, summary["modes"][0]["run_id"])
        self.assertTrue((self.output / "modes" / "vad-begin" / "report.json").is_file())
        self.assertTrue((self.output / "diagnostics" / failed.name / "report.json").is_file())
        self.assertFalse((self.output / "modes" / "vad-begin" / "payload" / "audio").exists())
        self.assertEqual("test precondition failed", summary["diagnostics"][0]["note"])
        for xml in self.output.glob("android-test-results/**/*.xml"):
            archived = xml.read_text(encoding="utf-8")
            self.assertIn('hostname="redacted"', archived)
            self.assertNotIn("private.local", archived)
            self.assertEqual("redacted", MODULE.ET.fromstring(archived).attrib["hostname"])

    def test_redacts_device_and_local_paths_from_every_text_artifact(self) -> None:
        self.make_run("20260807-100100-finish-shutdown-pass", "finish-shutdown", "PASS")
        run = self.raw / "20260807-100100-finish-shutdown-pass"
        (run / "hilog.txt").write_text(
            "network clientID=private 10.0.0.8 access TokenID=secret\n"
            f"ASR_STRESS|serial={self.device}|resultHex=e4bda0e5a5bd|source=/Users/private/work\n",
            encoding="utf-8",
        )
        report = json.loads((run / "report.json").read_text(encoding="utf-8"))
        report["resultHex"] = "e4bda0e5a5bd"
        (run / "report.json").write_text(json.dumps(report), encoding="utf-8")

        with mock.patch.object(MODULE, "REQUIRED_RELEASE_MODES", ("finish-shutdown",)):
            summary = MODULE.archive_evidence(
                raw_root=self.raw,
                output=self.output,
                release_version="0.3.1",
                source_commit="a" * 40,
                artifact_sha256="d" * 64,
                har_sha256="e" * 64,
                diagnostic_notes={},
                android_summary=self.android_summary,
                android_results_root=self.android_results,
                finish_compat_raw_root=self.finish_raw,
            )

        expected_alias = "device-" + hashlib.sha256(self.device.encode()).hexdigest()[:12]
        self.assertEqual(expected_alias, summary["device_alias"])
        for path in self.output.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(self.device, text, path)
            self.assertNotIn("/Users/private", text, path)
            self.assertNotIn("e4bda0e5a5bd", text, path)
            self.assertNotIn("clientID", text, path)

    def test_archives_numeric_gate_and_finish_compat_child_runs(self) -> None:
        self.make_run("20260807-100100-vad-begin-pass", "vad-begin", "PASS")
        finish_raw = self.root / "finish-raw"
        finish_runs = {}
        for mode in MODULE.REQUIRED_FINISH_COMPAT_MODES:
            run_id = f"20260807-100200-{mode}-pass"
            source = self.make_run(run_id, mode, "PASS")
            finish_raw.mkdir(exist_ok=True)
            shutil.move(str(source), finish_raw / run_id)
            finish_runs[mode] = run_id
        self.finish_summary.write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "source_commit": "a" * 40,
                    "modes": [
                        {"mode": mode, "run_id": run_id, "status": "PASS"}
                        for mode, run_id in finish_runs.items()
                    ],
                    "reports": {
                        mode: f"../finish-raw/{run_id}/report.json"
                        for mode, run_id in finish_runs.items()
                    },
                }
            ),
            encoding="utf-8",
        )
        numeric = self.root / "numeric.json"
        numeric.write_text(
            json.dumps(
                {
                    "gate": "numeric-identity-recovery",
                    "status": "PASS",
                    "source_commit": "a" * 40,
                    "hap_sha256": "c" * 64,
                    "input_sha256": "4" * 64,
                    "replay_report_sha256": "5" * 64,
                    "duration_ms": 10880,
                    "live_replay_exact_match": True,
                    "identifier_exact_match": True,
                    "identifier_length": 18,
                    "checksum_valid": True,
                    "lifecycle": {
                        "finish_before_last_count": 0,
                        "last_count": 1,
                        "complete_count": 1,
                        "errors": 0,
                        "live_streams": 0,
                    },
                }
            ),
            encoding="utf-8",
        )

        with mock.patch.object(MODULE, "REQUIRED_RELEASE_MODES", ("vad-begin",)):
            summary = MODULE.archive_evidence(
                raw_root=self.raw,
                output=self.output,
                release_version="0.3.1",
                source_commit="a" * 40,
                artifact_sha256="d" * 64,
                har_sha256="e" * 64,
                diagnostic_notes={},
                android_summary=self.android_summary,
                android_results_root=self.android_results,
                finish_compat_summary=self.finish_summary,
                finish_compat_raw_root=finish_raw,
                numeric_gate_attestation=numeric,
            )

        self.assertEqual(2, len(summary["finish_compat_runs"]))
        archived_finish = json.loads(
            (self.output / "finish-compat-report.json").read_text(encoding="utf-8")
        )
        for mode in MODULE.REQUIRED_FINISH_COMPAT_MODES:
            self.assertEqual(
                f"finish-compat-runs/{mode}/report.json",
                archived_finish["reports"][mode],
            )
            self.assertTrue(
                (self.output / "finish-compat-runs" / mode / "report.json").is_file()
            )
        self.assertEqual("4" * 64, summary["numeric_identity_gate"]["input_sha256"])
        self.assertTrue((self.output / "numeric-identity-gate.json").is_file())

    def test_rejects_missing_required_mode_and_existing_output(self) -> None:
        self.make_run("20260807-100100-vad-begin-pass", "vad-begin", "PASS")
        with mock.patch.object(
            MODULE, "REQUIRED_RELEASE_MODES", ("vad-begin", "finish-shutdown")
        ), self.assertRaisesRegex(MODULE.ArchiveFailure, "missing PASS reports"):
            MODULE.archive_evidence(
                raw_root=self.raw,
                output=self.output,
                release_version="0.3.1",
                source_commit="a" * 40,
                artifact_sha256="d" * 64,
                har_sha256="e" * 64,
                diagnostic_notes={},
                android_summary=self.android_summary,
                android_results_root=self.android_results,
                finish_compat_raw_root=self.finish_raw,
            )

        self.output.mkdir()
        with mock.patch.object(MODULE, "REQUIRED_RELEASE_MODES", ("vad-begin",)), \
             self.assertRaisesRegex(MODULE.ArchiveFailure, "already exists"):
            MODULE.archive_evidence(
                raw_root=self.raw,
                output=self.output,
                release_version="0.3.1",
                source_commit="a" * 40,
                artifact_sha256="d" * 64,
                har_sha256="e" * 64,
                diagnostic_notes={},
                android_summary=self.android_summary,
                android_results_root=self.android_results,
                finish_compat_raw_root=self.finish_raw,
            )

    def test_rejects_incomplete_android_matrix(self) -> None:
        self.make_run("20260807-100100-vad-begin-pass", "vad-begin", "PASS")
        payload = json.loads(self.android_summary.read_text(encoding="utf-8"))
        payload["suites"].pop()
        payload["total_tests"] = sum(item["tests"] for item in payload["suites"])
        self.android_summary.write_text(json.dumps(payload), encoding="utf-8")
        with mock.patch.object(MODULE, "REQUIRED_RELEASE_MODES", ("vad-begin",)), \
             self.assertRaisesRegex(MODULE.ArchiveFailure, "full Debug/Release matrix"):
            MODULE.archive_evidence(
                raw_root=self.raw,
                output=self.output,
                release_version="0.3.1",
                source_commit="a" * 40,
                artifact_sha256="d" * 64,
                har_sha256="e" * 64,
                diagnostic_notes={},
                android_summary=self.android_summary,
                android_results_root=self.android_results,
                finish_compat_raw_root=self.finish_raw,
            )

    def test_rejects_android_summary_that_disagrees_with_gradle_xml(self) -> None:
        self.make_run("20260807-100100-vad-begin-pass", "vad-begin", "PASS")
        payload = json.loads(self.android_summary.read_text(encoding="utf-8"))
        payload["suites"][0]["tests"] += 1
        payload["total_tests"] += 1
        self.android_summary.write_text(json.dumps(payload), encoding="utf-8")
        with mock.patch.object(MODULE, "REQUIRED_RELEASE_MODES", ("vad-begin",)), \
             self.assertRaisesRegex(MODULE.ArchiveFailure, "does not match summary"):
            MODULE.archive_evidence(
                raw_root=self.raw,
                output=self.output,
                release_version="0.3.1",
                source_commit="a" * 40,
                artifact_sha256="d" * 64,
                har_sha256="e" * 64,
                diagnostic_notes={},
                android_summary=self.android_summary,
                android_results_root=self.android_results,
                finish_compat_raw_root=self.finish_raw,
            )

    def test_rejects_component_har_drift_between_canonical_modes(self) -> None:
        self.make_run("20260807-100100-vad-begin-pass", "vad-begin", "PASS")
        finish = self.make_run(
            "20260807-100200-finish-shutdown-pass", "finish-shutdown", "PASS"
        )
        report = json.loads((finish / "report.json").read_text(encoding="utf-8"))
        report["build_identity"]["artifacts"]["amphion_asr.har"] = {
            "sha256": "0" * 64,
            "size_bytes": 1,
        }
        (finish / "report.json").write_text(json.dumps(report), encoding="utf-8")
        with mock.patch.object(
            MODULE, "REQUIRED_RELEASE_MODES", ("vad-begin", "finish-shutdown")
        ), self.assertRaisesRegex(MODULE.ArchiveFailure, "source/HAP/HAR identity"):
            MODULE.archive_evidence(
                raw_root=self.raw,
                output=self.output,
                release_version="0.3.1",
                source_commit="a" * 40,
                artifact_sha256="d" * 64,
                har_sha256="e" * 64,
                diagnostic_notes={},
                android_summary=self.android_summary,
                android_results_root=self.android_results,
                finish_compat_raw_root=self.finish_raw,
            )

    def test_rejects_component_har_without_a_sha256(self) -> None:
        run = self.make_run("20260807-100100-vad-begin-pass", "vad-begin", "PASS")
        report = json.loads((run / "report.json").read_text(encoding="utf-8"))
        report["build_identity"]["artifacts"]["amphion_asr.har"]["sha256"] = ""

        with self.assertRaisesRegex(MODULE.ArchiveFailure, "all four HAR SHA-256"):
            MODULE.identity_tuple(report)

    def test_rejects_delivery_har_that_was_not_tested_by_the_device_matrix(self) -> None:
        self.make_run("20260807-100100-vad-begin-pass", "vad-begin", "PASS")
        with mock.patch.object(MODULE, "REQUIRED_RELEASE_MODES", ("vad-begin",)), \
             self.assertRaisesRegex(MODULE.ArchiveFailure, "delivery HAR SHA-256"):
            MODULE.archive_evidence(
                raw_root=self.raw,
                output=self.output,
                release_version="0.3.1",
                source_commit="a" * 40,
                artifact_sha256="d" * 64,
                har_sha256="0" * 64,
                diagnostic_notes={},
                android_summary=self.android_summary,
                android_results_root=self.android_results,
                finish_compat_raw_root=self.finish_raw,
            )

    def test_rejects_device_matrix_from_another_verified_build_identity(self) -> None:
        self.make_run("20260807-100100-vad-begin-pass", "vad-begin", "PASS")
        identity = json.loads(self.build_identity.read_text(encoding="utf-8"))
        identity["artifacts"]["amphion_dingqiao.har"]["sha256"] = "0" * 64
        self.build_identity.write_text(json.dumps(identity), encoding="utf-8")
        with mock.patch.object(MODULE, "REQUIRED_RELEASE_MODES", ("vad-begin",)), \
             self.assertRaisesRegex(MODULE.ArchiveFailure, "verified Harmony build identity"):
            MODULE.archive_evidence(
                raw_root=self.raw,
                output=self.output,
                release_version="0.3.1",
                source_commit="a" * 40,
                artifact_sha256="d" * 64,
                har_sha256="e" * 64,
                diagnostic_notes={},
                android_summary=self.android_summary,
                android_results_root=self.android_results,
                finish_compat_raw_root=self.finish_raw,
                build_identity=self.build_identity,
            )

    def test_requires_a_run_longer_than_sixty_seconds(self) -> None:
        run = self.make_run("20260807-100100-vad-begin-pass", "vad-begin", "PASS")
        (run / "memory.csv").write_text(
            "elapsed_seconds,pid\n0,1\n60,1\n", encoding="utf-8"
        )
        with mock.patch.object(MODULE, "REQUIRED_RELEASE_MODES", ("vad-begin",)), \
             self.assertRaisesRegex(MODULE.ArchiveFailure, "no run longer than 60 seconds"):
            MODULE.archive_evidence(
                raw_root=self.raw,
                output=self.output,
                release_version="0.3.1",
                source_commit="a" * 40,
                artifact_sha256="d" * 64,
                har_sha256="e" * 64,
                diagnostic_notes={},
                android_summary=self.android_summary,
                android_results_root=self.android_results,
                finish_compat_raw_root=self.finish_raw,
            )

    def test_rejects_android_xml_older_than_release_commit(self) -> None:
        self.make_run("20260807-100100-vad-begin-pass", "vad-begin", "PASS")
        xml = next(self.android_results.glob("**/TEST-*.xml"))
        xml.write_text(
            xml.read_text(encoding="utf-8").replace(
                "2026-08-09T10:27:18", "2026-08-07T09:00:00"
            ),
            encoding="utf-8",
        )
        with mock.patch.object(MODULE, "REQUIRED_RELEASE_MODES", ("vad-begin",)), \
             self.assertRaisesRegex(MODULE.ArchiveFailure, "predates release source commit"):
            MODULE.archive_evidence(
                raw_root=self.raw,
                output=self.output,
                release_version="0.3.1",
                source_commit="a" * 40,
                artifact_sha256="d" * 64,
                har_sha256="e" * 64,
                diagnostic_notes={},
                android_summary=self.android_summary,
                android_results_root=self.android_results,
                finish_compat_raw_root=self.finish_raw,
            )


if __name__ == "__main__":
    unittest.main()
