import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("check_repository_versions.py")
SPEC = importlib.util.spec_from_file_location("check_repository_versions", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RepositoryVersionsTest(unittest.TestCase):
    def test_current_readme_matches_build_metadata(self) -> None:
        repo_root = MODULE_PATH.parents[1]
        versions = MODULE.read_versions(repo_root)
        readme = (repo_root / "README.md").read_text(encoding="utf-8")
        self.assertEqual(MODULE.find_source_violations(repo_root, versions), [])
        self.assertEqual(MODULE.find_readme_violations(readme, versions), [])

    def test_rejects_stale_version_and_unified_version_claim(self) -> None:
        readme = "整库版本号统一在 0.1.0\n| ASR Android | `0.1.0` | source |"
        violations = MODULE.find_readme_violations(readme, {"ASR Android": "0.3.4"})
        self.assertTrue(any("stale" in item for item in violations))
        self.assertTrue(any("single repository-wide" in item for item in violations))


if __name__ == "__main__":
    unittest.main()
