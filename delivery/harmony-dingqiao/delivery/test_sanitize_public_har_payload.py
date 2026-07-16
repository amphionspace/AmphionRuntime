from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("sanitize_public_har_payload.py")
SPEC = importlib.util.spec_from_file_location("sanitize_public_har_payload", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SanitizePublicHarPayloadTest(unittest.TestCase):
    def test_removes_internal_material_and_rebuilds_police_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "package"
            police = (
                package
                / "_bundled/amphion_police/src/main/resources/rawfile/amphion-police"
            )
            police.mkdir(parents=True)
            (package / "CONTRACT_TESTS.md").write_text("internal\n", encoding="utf-8")
            (package / "oh-package-lock.json5").write_text("{}\n", encoding="utf-8")
            tests = police.parent.parent / "tests/police_v2_parity.tsv"
            tests.parent.mkdir(parents=True)
            tests.write_text("secret fixture\n", encoding="utf-8")
            model_readme = (
                package
                / "_bundled/amphion_asr/src/main/resources/rawfile/amphion-models/README.md"
            )
            model_readme.parent.mkdir(parents=True)
            model_readme.write_text("internal model notes\n", encoding="utf-8")

            meta = police / "area/rules_meta.json"
            data = police / "area/rules.csv"
            meta.parent.mkdir(parents=True)
            meta.write_text('{"source":"/Users/example/input.csv"}\n', encoding="utf-8")
            data.write_text("# internal batch\nfrom,to\n甲,乙\n", encoding="utf-8")
            manifest = police / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "files": {
                            "area/rules_meta.json": hashlib.sha256(meta.read_bytes()).hexdigest(),
                            "area/rules.csv": hashlib.sha256(data.read_bytes()).hexdigest(),
                        },
                    }
                ),
                encoding="utf-8",
            )

            MODULE.sanitize_payload(package)

            self.assertFalse((package / "CONTRACT_TESTS.md").exists())
            self.assertFalse((package / "oh-package-lock.json5").exists())
            self.assertFalse(tests.parent.exists())
            self.assertFalse(model_readme.exists())
            self.assertFalse(meta.exists())
            self.assertEqual("from,to\n甲,乙\n", data.read_text(encoding="utf-8"))
            public_manifest = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual({"area/rules.csv"}, set(public_manifest["files"]))
            self.assertEqual(
                hashlib.sha256(data.read_bytes()).hexdigest(),
                public_manifest["files"]["area/rules.csv"],
            )


if __name__ == "__main__":
    unittest.main()
