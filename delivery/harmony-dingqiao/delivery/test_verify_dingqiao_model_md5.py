from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
import zipfile


SCRIPT = Path(__file__).with_name("verify_dingqiao_model_md5.py")
SPEC = importlib.util.spec_from_file_location("verify_dingqiao_model_md5", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class VerifyDingqiaoModelMd5Test(unittest.TestCase):
    def setUp(self) -> None:
        self.payloads = {
            "zh-en/v1/encoder.int8.ort": b"encoder",
            "zh-en/v1/decoder.ort": b"decoder",
            "zh-en/v1/joiner.int8.ort": b"joiner",
            "zh-en/v1/tokens.txt": b"tokens",
            "zh-en/v1/bbpe.vocab": b"vocab",
        }
        self.expected = {
            relative: hashlib.md5(payload).hexdigest()
            for relative, payload in self.payloads.items()
        }

    def test_default_policy_pins_complete_runtime_file_set(self) -> None:
        model_id, expected = MODULE.load_policy()
        self.assertEqual("transducer-chunk32-lc256-260717", model_id)
        self.assertEqual(MODULE.REQUIRED_RUNTIME_FILES, set(expected))

    def _write_root(self, root: Path) -> None:
        for relative, payload in self.payloads.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)

    def _write_tar(self, path: Path, *, alter_encoder: bool = False) -> None:
        prefix = (
            "package/_bundled/amphion_asr/src/main/resources/rawfile/amphion-models"
        )
        with tarfile.open(path, "w:gz") as archive:
            for relative, original in self.payloads.items():
                payload = b"wrong" if alter_encoder and "encoder" in relative else original
                info = tarfile.TarInfo(f"{prefix}/{relative}")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))

    def _write_zip(self, path: Path, *, alter_encoder: bool = False) -> None:
        prefix = "resources/rawfile/amphion-models"
        with zipfile.ZipFile(path, "w") as archive:
            for relative, original in self.payloads.items():
                payload = b"wrong" if alter_encoder and "encoder" in relative else original
                archive.writestr(f"{prefix}/{relative}", payload)

    def test_accepts_exact_root_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_root(root)
            MODULE.verify_root(root, self.expected)

    def test_rejects_changed_root_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_root(root)
            (root / "zh-en/v1/encoder.int8.ort").write_bytes(b"wrong")
            with self.assertRaisesRegex(MODULE.ModelIdentityError, "MD5 mismatch"):
                MODULE.verify_root(root, self.expected)

    def test_accepts_exact_har_and_hap_models(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            har = root / "sdk.har"
            hap = root / "demo.hap"
            self._write_tar(har)
            self._write_zip(hap)
            MODULE.verify_archive(har, self.expected)
            MODULE.verify_archive(hap, self.expected)

    def test_rejects_changed_archive_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            har = Path(directory) / "sdk.har"
            self._write_tar(har, alter_encoder=True)
            with self.assertRaisesRegex(MODULE.ModelIdentityError, "MD5 mismatch"):
                MODULE.verify_archive(har, self.expected)

    def test_rejects_changed_hap_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hap = Path(directory) / "demo.hap"
            self._write_zip(hap, alter_encoder=True)
            with self.assertRaisesRegex(MODULE.ModelIdentityError, "MD5 mismatch"):
                MODULE.verify_archive(hap, self.expected)

    def test_rejects_duplicate_archive_model_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            duplicate = Path(directory) / "duplicate.har"
            prefix = "resources/rawfile/amphion-models"
            with tarfile.open(duplicate, "w:gz") as archive:
                for relative, payload in self.payloads.items():
                    for root in ("package/a", "package/b") if "encoder" in relative else ("package/a",):
                        info = tarfile.TarInfo(f"{root}/{prefix}/{relative}")
                        info.size = len(payload)
                        archive.addfile(info, io.BytesIO(payload))
            with self.assertRaisesRegex(MODULE.ModelIdentityError, "multiple archive members"):
                MODULE.verify_archive(duplicate, self.expected)


if __name__ == "__main__":
    unittest.main()
