from __future__ import annotations

import hashlib
import importlib.util
import io
import json
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
            source: hashlib.sha256(source.encode()).hexdigest()
            for source in MODULE.RUNTIME_TO_SOURCE.values()
        }

    def test_default_policy_pins_complete_source_file_set(self) -> None:
        model_id, expected = MODULE.load_policy()
        self.assertEqual("transducer-chunk32-lc256-260717", model_id)
        self.assertEqual(set(MODULE.RUNTIME_TO_SOURCE.values()), set(expected))

    def _manifest(self, payloads: dict[str, bytes] | None = None) -> dict:
        payloads = payloads or self.payloads
        return {
            "manifest_version": 2,
            "bundles": {
                "zh-en/v1": [
                    {
                        "name": name.rsplit("/", 1)[-1],
                        "source_name": MODULE.RUNTIME_TO_SOURCE[name.rsplit("/", 1)[-1]],
                        "source_sha256": self.expected[
                            MODULE.RUNTIME_TO_SOURCE[name.rsplit("/", 1)[-1]]
                        ],
                        "output_sha256": hashlib.sha256(payload).hexdigest(),
                    }
                    for name, payload in payloads.items()
                ]
            },
        }

    def _write_root(self, root: Path) -> None:
        for relative, payload in self.payloads.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        (root / "manifest.json").write_text(json.dumps(self._manifest()), encoding="utf-8")

    def _write_tar(self, path: Path, *, alter_encoder: bool = False) -> None:
        prefix = (
            "package/_bundled/amphion_asr/src/main/resources/rawfile/amphion-models"
        )
        with tarfile.open(path, "w:gz") as archive:
            manifest = json.dumps(self._manifest()).encode()
            info = tarfile.TarInfo(f"{prefix}/manifest.json")
            info.size = len(manifest)
            archive.addfile(info, io.BytesIO(manifest))
            for relative, original in self.payloads.items():
                payload = b"wrong" if alter_encoder and "encoder" in relative else original
                info = tarfile.TarInfo(f"{prefix}/{relative}")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))

    def _write_zip(self, path: Path, *, alter_encoder: bool = False) -> None:
        prefix = "resources/rawfile/amphion-models"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(f"{prefix}/manifest.json", json.dumps(self._manifest()))
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
            with self.assertRaisesRegex(MODULE.ModelIdentityError, "runtime SHA-256 mismatch"):
                MODULE.verify_root(root, self.expected)

    def test_accepts_rebuilt_ort_with_same_onnx_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rebuilt = dict(self.payloads)
            rebuilt["zh-en/v1/encoder.int8.ort"] = b"different valid ORT bytes"
            for relative, payload in rebuilt.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            (root / "manifest.json").write_text(
                json.dumps(self._manifest(rebuilt)), encoding="utf-8"
            )
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
            with self.assertRaisesRegex(MODULE.ModelIdentityError, "runtime SHA-256 mismatch"):
                MODULE.verify_archive(har, self.expected)

    def test_rejects_changed_hap_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hap = Path(directory) / "demo.hap"
            self._write_zip(hap, alter_encoder=True)
            with self.assertRaisesRegex(MODULE.ModelIdentityError, "runtime SHA-256 mismatch"):
                MODULE.verify_archive(hap, self.expected)

    def test_rejects_duplicate_archive_model_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            duplicate = Path(directory) / "duplicate.har"
            prefix = "resources/rawfile/amphion-models"
            with tarfile.open(duplicate, "w:gz") as archive:
                manifest = json.dumps(self._manifest()).encode()
                info = tarfile.TarInfo(f"package/a/{prefix}/manifest.json")
                info.size = len(manifest)
                archive.addfile(info, io.BytesIO(manifest))
                for relative, payload in self.payloads.items():
                    for root in ("package/a", "package/b") if "encoder" in relative else ("package/a",):
                        info = tarfile.TarInfo(f"{root}/{prefix}/{relative}")
                        info.size = len(payload)
                        archive.addfile(info, io.BytesIO(payload))
            with self.assertRaisesRegex(MODULE.ModelIdentityError, "exactly one model runtime"):
                MODULE.verify_archive(duplicate, self.expected)


if __name__ == "__main__":
    unittest.main()
