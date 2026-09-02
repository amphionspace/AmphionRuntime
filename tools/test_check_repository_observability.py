import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("check_repository_observability.py")
SPEC = importlib.util.spec_from_file_location("check_repository_observability", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RepositoryObservabilityTest(unittest.TestCase):
    def check(self, relative: str, content: str) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / relative
            path.parent.mkdir(parents=True)
            path.write_text(content, encoding="utf-8")
            return MODULE.find_violations(root, [relative])

    def test_accepts_redacted_release_evidence(self) -> None:
        relative = "delivery/harmony-dingqiao/evidence/run/report.json"
        content = json.dumps({"device": "device-9d33cec60055", "resultHex": "<redacted>"})
        self.assertEqual(self.check(relative, content), [])

    def test_rejects_raw_identifiers_and_local_paths(self) -> None:
        relative = "delivery/harmony-dingqiao/evidence/run/report.json"
        content = json.dumps({"serial": "7GK0226326015655", "source": "/Users/person/audio"})
        violations = self.check(relative, content)
        self.assertTrue(any("device identifier" in item for item in violations))
        self.assertTrue(any("local home path" in item for item in violations))

    def test_rejects_unredacted_result_hex(self) -> None:
        violations = self.check(
            "delivery/harmony-dingqiao/evidence/run/result.txt", "resultHex=4f60597d"
        )
        self.assertTrue(any("recognition text" in item for item in violations))

    def test_rejects_full_system_logs_by_path(self) -> None:
        violations = self.check("asr/android/reports/run/evidence/logcat.txt", "system log")
        self.assertTrue(any("raw system log" in item for item in violations))

    def test_rejects_private_home_paths_in_docs_and_reports(self) -> None:
        for relative in ("docs/report.md", "asr/server/reports/run.json"):
            with self.subTest(relative=relative):
                violations = self.check(relative, "/Users/alice/private/input.wav")
                self.assertTrue(any("local home path" in item for item in violations))

    def test_accepts_portable_home_path_examples(self) -> None:
        self.assertEqual(self.check("docs/setup.md", "/Users/you/project"), [])
        self.assertEqual(self.check("docs/setup.md", "/home/user/project"), [])

    def test_rejects_raw_operation_log(self) -> None:
        violations = self.check("docs/OPERATION_LOG.md", "no sensitive text")
        self.assertTrue(any("operation log" in item for item in violations))


if __name__ == "__main__":
    unittest.main()
