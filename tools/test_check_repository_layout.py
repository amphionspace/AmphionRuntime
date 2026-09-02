import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("check_repository_layout.py")
SPEC = importlib.util.spec_from_file_location("check_repository_layout", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RepositoryLayoutTest(unittest.TestCase):
    def valid_paths(self) -> set[str]:
        return {"README.md", "AGENTS.md", *MODULE.REQUIRED_FILES}

    def test_accepts_module_owned_documents(self) -> None:
        self.assertEqual(MODULE.find_path_violations(self.valid_paths()), [])

    def test_rejects_root_markdown(self) -> None:
        violations = MODULE.find_path_violations({*self.valid_paths(), "SDK_API.md"})
        self.assertTrue(any("root Markdown" in item for item in violations))

    def test_rejects_unowned_root_directory(self) -> None:
        violations = MODULE.find_path_violations(
            {*self.valid_paths(), "standalone_training_project/train.py"}
        )
        self.assertTrue(any("root directory is not module-owned" in item for item in violations))

    def test_rejects_trailing_whitespace_component(self) -> None:
        violations = MODULE.find_path_violations({*self.valid_paths(), "test /cases.jsonl"})
        self.assertTrue(any("trailing whitespace" in item for item in violations))

    def test_rejects_root_license_delivery_directory(self) -> None:
        paths = {*self.valid_paths(), "amphion-dingqiao-license-v1.0/VERSION.txt"}
        violations = MODULE.find_path_violations(paths)
        self.assertTrue(any("license delivery directory" in item for item in violations))

    def test_rejects_legacy_tts_tooling_locations(self) -> None:
        for legacy_path in MODULE.LEGACY_TTS_PATHS:
            with self.subTest(legacy_path=legacy_path):
                violations = MODULE.find_path_violations({*self.valid_paths(), legacy_path})
                self.assertTrue(any("TTS tooling" in item for item in violations))

    def test_rejects_legacy_asr_tooling_locations(self) -> None:
        for legacy_path in MODULE.LEGACY_ASR_PATHS:
            with self.subTest(legacy_path=legacy_path):
                violations = MODULE.find_path_violations({*self.valid_paths(), legacy_path})
                self.assertTrue(any("ASR tooling" in item for item in violations))

    def test_rejects_local_only_submodule_pin(self) -> None:
        gitlinks = {"third_party/sherpa-onnx": "74e48a3606ac9bac38f4912b1836da53ef7f4bb2"}
        violations = MODULE.find_gitlink_violations(gitlinks)
        self.assertTrue(any("reproducible upstream pin" in item for item in violations))

    def test_rejects_missing_required_document(self) -> None:
        paths = self.valid_paths() - {"tts/docs/api/语音合成SDK接口.md"}
        violations = MODULE.find_path_violations(paths)
        self.assertTrue(any("required module document" in item for item in violations))

    def test_rejects_local_path_in_fixture_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo_root = Path(directory)
            summary_dir = repo_root / "tts/android/testdata/dingqiao_batch_cases"
            summary_dir.mkdir(parents=True)
            (summary_dir / "sample_summary.json").write_text(
                json.dumps({"jsonl": "/Users/example/private/cases.jsonl"}),
                encoding="utf-8",
            )
            violations = MODULE.find_summary_violations(repo_root)
        self.assertTrue(any("local absolute path" in item for item in violations))


if __name__ == "__main__":
    unittest.main()
