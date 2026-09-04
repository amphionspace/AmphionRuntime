import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("runner.py")
SPEC = importlib.util.spec_from_file_location("dashboard_runner", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class DashboardRunnerSecurityTest(unittest.TestCase):
    def test_rejects_invalid_or_path_traversal_month(self) -> None:
        for value in ("2026-13", "../../tmp/report", "2026-09; touch /tmp/pwned"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                MODULE.validate_month(value)

    def test_load_json_source_does_not_execute_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bench.json"
            source.write_text('{"max_concurrency": 4}', encoding="utf-8")
            with mock.patch.object(MODULE.subprocess, "run") as run:
                payload = MODULE.load_json_source(source, "bench")

        self.assertEqual(payload, {"max_concurrency": 4})
        run.assert_not_called()

    def test_load_json_source_rejects_oversized_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bench.json"
            with source.open("wb") as stream:
                stream.truncate(MODULE.MAX_JSON_BYTES + 1)
            with self.assertRaises(ValueError):
                MODULE.load_json_source(source, "bench")

    def test_parses_repository_benchmark_schema(self) -> None:
        stats = MODULE.parse_server_bench(
            {
                "concurrency": 16,
                "sessions": 100,
                "failures": 2,
                "rtf": {"p50": 0.2, "p99": 0.4},
                "first_partial_ms": {"p95": 450},
            }
        )

        self.assertEqual(stats.max_concurrency, 16)
        self.assertEqual(stats.error_rate, 2.0)
        self.assertEqual(stats.first_partial_p95, 450.0)

    def test_markdown_table_cells_cannot_break_rows(self) -> None:
        rendered = MODULE.render_table_rows(
            [{"issue": "boom | @all\n<script>alert(1)</script>"}], ["issue"]
        )

        self.assertEqual(rendered.count("\n"), 0)
        self.assertNotIn("<script>", rendered)
        self.assertIn(r"\|", rendered)

    def test_report_url_cannot_inject_markdown_or_credentials(self) -> None:
        self.assertEqual(
            MODULE.safe_report_url("https://reports.example/wer/2026-09.html"),
            "https://reports.example/wer/2026-09.html",
        )
        for value in (
            "http://reports.example/wer",
            "https://user:secret@reports.example/wer",
            "https://reports.example/wer)\n<script>alert(1)</script>",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                MODULE.safe_report_url(value)


if __name__ == "__main__":
    unittest.main()
