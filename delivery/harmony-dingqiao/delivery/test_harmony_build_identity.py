from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name("harmony_build_identity.py")
SPEC = importlib.util.spec_from_file_location("harmony_build_identity", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SoleHarTest(unittest.TestCase):
    def test_requires_exactly_one_har(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(MODULE.IdentityFailure, "expected one HAR"):
                MODULE.sole_har(root)
            (root / "one.har").write_bytes(b"one")
            self.assertEqual(root / "one.har", MODULE.sole_har(root))
            (root / "two.har").write_bytes(b"two")
            with self.assertRaisesRegex(MODULE.IdentityFailure, "found 2"):
                MODULE.sole_har(root)


class VerifyIdentityTest(unittest.TestCase):
    def test_rejects_stale_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            path.write_text(json.dumps({"git_commit": "old"}), encoding="utf-8")
            with mock.patch.object(MODULE, "current_identity", return_value={"git_commit": "new"}):
                with self.assertRaisesRegex(MODULE.IdentityFailure, "stale"):
                    MODULE.verify_identity(path)

    def test_accepts_created_at_as_non_identity_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            path.write_text(
                json.dumps({"git_commit": "same", "created_at": "timestamp"}), encoding="utf-8"
            )
            with mock.patch.object(MODULE, "current_identity", return_value={"git_commit": "same"}):
                MODULE.verify_identity(path)


if __name__ == "__main__":
    unittest.main()
