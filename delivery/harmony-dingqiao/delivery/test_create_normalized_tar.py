from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("create_normalized_tar.py")
SPEC = importlib.util.spec_from_file_location("create_normalized_tar", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CreateNormalizedTarTest(unittest.TestCase):
    def test_normalizes_archive_metadata_and_ignores_xattrs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "package"
            root.mkdir()
            payload = root / "asset.txt"
            payload.write_text("payload\n", encoding="utf-8")
            try:
                payload.chmod(0o644)
            except OSError:
                pass
            archive_path = Path(directory) / "sdk.har"
            MODULE.create_archive(root, archive_path)
            with tarfile.open(archive_path, "r:gz") as archive:
                members = archive.getmembers()
            self.assertEqual(["package", "package/asset.txt"], [m.name for m in members])
            for member in members:
                self.assertEqual(0, member.uid)
                self.assertEqual(0, member.gid)
                self.assertEqual("", member.uname)
                self.assertEqual("", member.gname)
                self.assertEqual(0, member.mtime)
                self.assertEqual({}, member.pax_headers)
                self.assertFalse(Path(member.name).name.startswith("._"))

    def test_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "package"
            root.mkdir()
            target = root / "target.txt"
            target.write_text("target\n", encoding="utf-8")
            (root / "link.txt").symlink_to(target.name)
            with self.assertRaisesRegex(MODULE.NormalizedTarError, "symlink"):
                MODULE.create_archive(root, Path(directory) / "sdk.har")


if __name__ == "__main__":
    unittest.main()
