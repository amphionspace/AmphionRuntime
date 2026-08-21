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
        command = diagnostics.build_recv_command(Path("/opt/hdc"), "SAFE", Path("/tmp/out"))
        self.assertEqual(
            command,
            ["/opt/hdc", "-t", "SAFE", "file", "recv", "-b", diagnostics.BUNDLE,
             diagnostics.REMOTE_ROOT, "/tmp/out"],
        )

    def test_validate_run_accepts_complete_redacted_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = self.make_run(Path(directory))
            result = diagnostics.validate_run(run)
            self.assertEqual(result["manifest"]["runId"], "run-100")

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


if __name__ == "__main__":
    unittest.main()
