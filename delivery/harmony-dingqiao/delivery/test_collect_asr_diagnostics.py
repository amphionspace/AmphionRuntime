import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_asr_diagnostics as diagnostics


class CollectAsrDiagnosticsTest(unittest.TestCase):
    def make_run(self, root: Path, run_id: str = "run-100") -> Path:
        run = root / run_id
        session = run / "sessions/session-1"
        session.mkdir(parents=True)
        (run / "manifest.json").write_text(
            json.dumps({"schemaVersion": 1, "runId": run_id}), encoding="utf-8"
        )
        (run / "summary.json").write_text(json.dumps({"runId": run_id}), encoding="utf-8")
        event = {"event": "CALLBACK_RESULT", "fields": {"isLast": True}}
        (run / "events.ndjson").write_text(json.dumps(event) + "\n", encoding="utf-8")
        (run / "callbacks.ndjson").write_text(json.dumps(event) + "\n", encoding="utf-8")
        (session / "sdk-input.json").write_text(json.dumps({"bytes": 4}), encoding="utf-8")
        (session / "sdk-input.wav").write_bytes(b"RIFF" + bytes(44))
        return run

    def test_build_recv_command_uses_app_sandbox(self) -> None:
        command = diagnostics.build_recv_command(
            Path("/opt/hdc"), "SAFE", Path("/tmp/out"), "com.example.app", "entry"
        )
        self.assertEqual(
            command,
            ["/opt/hdc", "-t", "SAFE", "file", "recv", "-b", "com.example.app",
             "/data/storage/el2/base/haps/entry/files/asr-diagnostics", "/tmp/out"],
        )

    def test_discover_module_reads_bm_dump(self) -> None:
        from unittest.mock import patch

        completed = __import__("subprocess").CompletedProcess(
            [], 0, '{"moduleName":"entry","nested":{"moduleName":"entry"}}', ""
        )
        with patch.object(diagnostics.subprocess, "run", return_value=completed):
            self.assertEqual(
                diagnostics.discover_module(Path("/opt/hdc"), "SAFE", "com.example.app"),
                "entry",
            )

    def test_validate_run_accepts_complete_redacted_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = self.make_run(Path(directory))
            result = diagnostics.validate_run(run)
            self.assertEqual(result["manifest"]["runId"], "run-100")

    def test_validate_run_accepts_schema_two_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = self.make_run(Path(directory))
            (run / "manifest.json").write_text(
                json.dumps({"schemaVersion": 2, "runId": "run-100"}), encoding="utf-8"
            )
            for name in (
                "build-identity.json",
                "model-manifest.json",
                "effective-config.json",
                "native-state.json",
            ):
                (run / name).write_text("{}", encoding="utf-8")
            (run / "resource-samples.csv").write_text(
                "wallTimeMs,rssKb,anonymousRssKb\n1,2,3\n", encoding="utf-8"
            )
            session = run / "sessions/session-1"
            (session / "timeline.json").write_text("[]", encoding="utf-8")
            (session / "result.json").write_text("{}", encoding="utf-8")
            result = diagnostics.validate_run(run)
            self.assertEqual(result["manifest"]["schemaVersion"], 2)

    def test_validate_run_rejects_sensitive_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = self.make_run(Path(directory))
            (run / "events.ndjson").write_text(
                json.dumps({"fields": {"voiceprintId": "secret"}}) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(RuntimeError, "forbidden field"):
                diagnostics.validate_run(run)

    def test_redact_hilog_removes_device_paths_and_secrets(self) -> None:
        source = "SERIAL /data/storage/el2/base/files/a license=abc hotwords=张三"
        redacted = diagnostics.redact_hilog(source, "SERIAL")
        self.assertNotIn("SERIAL", redacted)
        self.assertNotIn("/data/storage", redacted)
        self.assertNotIn("abc", redacted)
        self.assertNotIn("张三", redacted)

    def test_collect_hilog_uses_bounded_non_blocking_dump(self) -> None:
        from unittest.mock import patch

        source = (
            "08-21 16:00:00.000 123 124 I A00000/com.example.app/SDK: keep\n"
            "08-21 16:00:00.001 123 125 I A00000/native/ASR: keep native\n"
            "08-21 16:00:00.002 999 999 I A00000/other/App: drop\n"
        )
        completed = __import__("subprocess").CompletedProcess([], 0, source, "")
        with patch.object(diagnostics.subprocess, "run", return_value=completed) as run:
            output = diagnostics.collect_hilog(Path("/opt/hdc"), "SAFE", "com.example.app")
            self.assertIn("keep native", output)
            self.assertNotIn("drop", output)
        self.assertEqual(
            run.call_args.args[0],
            ["/opt/hdc", "-t", "SAFE", "shell", "hilog", "-x"],
        )
        self.assertEqual(run.call_args.kwargs["timeout"], 30)


if __name__ == "__main__":
    unittest.main()
