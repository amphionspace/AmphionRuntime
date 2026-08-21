import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pull_demo_cases


class PullDemoCasesTest(unittest.TestCase):
    def test_build_recv_command_uses_the_app_sandbox(self) -> None:
        command = pull_demo_cases.build_recv_command(
            Path("/opt/hdc"), "SAFE_DEVICE", Path("/tmp/cases")
        )

        self.assertEqual(
            command,
            [
                "/opt/hdc", "-t", "SAFE_DEVICE", "file", "recv", "-b",
                "com.amphion.asr.harmony.debug",
                "/data/storage/el2/base/files/asr-cases",
                "/tmp/cases",
            ],
        )

    def test_validate_case_tree_requires_the_three_case_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_dir = root / "case-123"
            case_dir.mkdir()
            (case_dir / "audio.wav").write_bytes(b"RIFF")
            (case_dir / "note.txt").write_text("近讲", encoding="utf-8")
            (case_dir / "metadata.json").write_text(
                json.dumps({"caseId": "case-123", "note": "近讲"}), encoding="utf-8"
            )

            cases = pull_demo_cases.validate_case_tree(root)

            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0]["caseId"], "case-123")
            self.assertEqual(cases[0]["note"], "近讲")

    def test_validate_case_tree_rejects_incomplete_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_dir = root / "case-123"
            case_dir.mkdir()
            (case_dir / "metadata.json").write_text(
                json.dumps({"caseId": "case-123"}), encoding="utf-8"
            )

            with self.assertRaisesRegex(RuntimeError, "missing audio.wav"):
                pull_demo_cases.validate_case_tree(root)

    def test_validate_case_tree_rejects_note_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_dir = root / "case-123"
            case_dir.mkdir()
            (case_dir / "audio.wav").write_bytes(b"RIFF")
            (case_dir / "note.txt").write_text("车内", encoding="utf-8")
            (case_dir / "metadata.json").write_text(
                json.dumps({"caseId": "case-123", "note": "近讲"}), encoding="utf-8"
            )

            with self.assertRaisesRegex(RuntimeError, "note does not match"):
                pull_demo_cases.validate_case_tree(root)


if __name__ == "__main__":
    unittest.main()
