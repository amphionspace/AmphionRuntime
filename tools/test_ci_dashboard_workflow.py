import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/dashboard.yml"
MIRROR = ROOT / "ci/dashboard.yml"


class DashboardWorkflowSecurityTest(unittest.TestCase):
    def test_workflow_is_read_only_and_does_not_publish_reports(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("git push", workflow)
        self.assertNotIn("gh pr create", workflow)

    def test_remote_archives_use_validated_extraction(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("tools/ci/secure_extract_tar.py", workflow)
        self.assertNotIn("tar xf /tmp/wav.tar.gz", workflow)
        self.assertIn("--max-filesize", workflow)

    def test_workflow_does_not_connect_to_benchmark_service(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("BENCH_JSON_URL", workflow)
        self.assertNotIn("BENCH_TARGET", workflow)
        self.assertNotIn("pip install", workflow)

    def test_workflow_mirror_is_identical(self) -> None:
        self.assertEqual(
            WORKFLOW.read_text(encoding="utf-8"),
            MIRROR.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
