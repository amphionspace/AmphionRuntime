import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from secure_extract_tar import UnsafeArchiveError, extract_tar


class SecureExtractTarTest(unittest.TestCase):
    def write_archive(self, root: Path, name: str, *, kind: bytes = tarfile.REGTYPE) -> Path:
        archive_path = root / "input.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            info = tarfile.TarInfo(name)
            info.type = kind
            data = b"wave"
            info.size = len(data) if kind == tarfile.REGTYPE else 0
            archive.addfile(info, io.BytesIO(data) if info.size else None)
        return archive_path

    def test_extracts_regular_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self.write_archive(root, "corpus/sample.wav")
            destination = root / "out"
            extract_tar(archive, destination)
            self.assertEqual((destination / "corpus/sample.wav").read_bytes(), b"wave")

    def test_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self.write_archive(root, "../outside.txt")
            with self.assertRaises(UnsafeArchiveError):
                extract_tar(archive, root / "out")
            self.assertFalse((root / "outside.txt").exists())

    def test_rejects_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self.write_archive(root, "corpus/link", kind=tarfile.SYMTYPE)
            with self.assertRaises(UnsafeArchiveError):
                extract_tar(archive, root / "out")

    def test_rejects_existing_destination_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self.write_archive(root, "linked/outside.txt")
            destination = root / "out"
            destination.mkdir()
            outside = root / "outside"
            outside.mkdir()
            (destination / "linked").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(UnsafeArchiveError):
                extract_tar(archive, destination)
            self.assertFalse((outside / "outside.txt").exists())


if __name__ == "__main__":
    unittest.main()
