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
ASSET_PACKER = SCRIPT.parents[3] / "asr/tools/08_pack_harmony_assets.sh"
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
            source: hashlib.md5(source.encode()).hexdigest()
            for source in MODULE.RUNTIME_TO_ONNX_SOURCE.values()
        }

    def test_default_policy_pins_police_candidate_onnx_md5(self) -> None:
        model_id, expected = MODULE.load_policy()
        policy = json.loads(MODULE.DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            "police-179m-v1-1-1.1.0-chunk32-lc256-edge-transducer",
            model_id,
        )
        self.assertEqual(
            "6fd85a43dd226d7aa6f0db5b84be8c92",
            policy["source_bundle"]["md5"],
        )
        self.assertEqual(
            {
                "encoder.int8.onnx": "0bcad6878250a88261de9d4ca1129047",
                "decoder.onnx": "5eda4a3e47144bcea5b110e3ebf2469e",
                "joiner.onnx": "5d408055735dd5275076a099d8c505f0",
            },
            expected,
        )

    def test_asset_packer_uses_the_pinned_fp32_joiner(self) -> None:
        script = ASSET_PACKER.read_text(encoding="utf-8")
        self.assertIn('convert_one "${ZH_EN_DIR}/joiner.onnx"', script)
        self.assertNotIn('convert_one "${ZH_EN_DIR}/joiner.int8.onnx"', script)

    def test_asset_packer_supports_zh_en_only_delivery(self) -> None:
        script = ASSET_PACKER.read_text(encoding="utf-8")
        self.assertIn("--zh-en-only", script)
        self.assertIn('if [[ "$ZH_EN_ONLY" != true ]]; then', script)
        self.assertIn("verify_args+=(--zh-en-only)", script)

    def _manifest(self, *, wrong_source_md5: bool = False) -> dict:
        entries = []
        for relative, payload in self.payloads.items():
            runtime_name = relative.rsplit("/", 1)[-1]
            source_name = MODULE.RUNTIME_TO_ONNX_SOURCE.get(runtime_name, runtime_name)
            source_md5 = self.expected.get(
                source_name, hashlib.md5(source_name.encode()).hexdigest()
            )
            if wrong_source_md5 and runtime_name == "encoder.int8.ort":
                source_md5 = "0" * 32
            entries.append(
                {
                    "name": runtime_name,
                    "source_name": source_name,
                    "source_md5": source_md5,
                    # Deliberately unrelated: model identity must not use source SHA-256.
                    "source_sha256": "f" * 64,
                    "output_sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
        return {"manifest_version": 2, "bundles": {"zh-en/v1": entries}}

    def _write_root(self, root: Path) -> None:
        for relative, payload in self.payloads.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        (root / "manifest.json").write_text(
            json.dumps(self._manifest()), encoding="utf-8"
        )

    def _write_tar(self, path: Path, *, wrong_source_md5: bool = False) -> None:
        prefix = "package/_bundled/amphion_asr/src/main/resources/rawfile/amphion-models"
        with tarfile.open(path, "w:gz") as archive:
            manifest = json.dumps(
                self._manifest(wrong_source_md5=wrong_source_md5)
            ).encode()
            info = tarfile.TarInfo(f"{prefix}/manifest.json")
            info.size = len(manifest)
            archive.addfile(info, io.BytesIO(manifest))
            for relative, payload in self.payloads.items():
                info = tarfile.TarInfo(f"{prefix}/{relative}")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))

    def _write_zip(self, path: Path) -> None:
        prefix = "resources/rawfile/amphion-models"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(f"{prefix}/manifest.json", json.dumps(self._manifest()))
            for relative, payload in self.payloads.items():
                archive.writestr(f"{prefix}/{relative}", payload)

    def test_accepts_exact_root_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_root(root)
            MODULE.verify_root(root, self.expected)

    def test_model_identity_ignores_runtime_ort_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_root(root)
            (root / "zh-en/v1/encoder.int8.ort").write_bytes(b"different ORT build")
            MODULE.verify_root(root, self.expected)

    def test_rejects_wrong_onnx_md5(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_root(root)
            manifest = self._manifest(wrong_source_md5=True)
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ModelIdentityError, "ONNX MD5 mismatch"):
                MODULE.verify_root(root, self.expected)

    def test_accepts_har_and_hap_from_manifest_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            har = root / "sdk.har"
            hap = root / "demo.hap"
            self._write_tar(har)
            self._write_zip(hap)
            MODULE.verify_archive(har, self.expected)
            MODULE.verify_archive(hap, self.expected)

    def test_rejects_archive_with_wrong_onnx_md5(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            har = Path(directory) / "sdk.har"
            self._write_tar(har, wrong_source_md5=True)
            with self.assertRaisesRegex(MODULE.ModelIdentityError, "ONNX MD5 mismatch"):
                MODULE.verify_archive(har, self.expected)

    def test_rejects_duplicate_archive_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            duplicate = Path(directory) / "duplicate.har"
            manifest = json.dumps(self._manifest()).encode()
            with tarfile.open(duplicate, "w:gz") as archive:
                for root in ("package/a", "package/b"):
                    info = tarfile.TarInfo(
                        f"{root}/resources/rawfile/amphion-models/manifest.json"
                    )
                    info.size = len(manifest)
                    archive.addfile(info, io.BytesIO(manifest))
            with self.assertRaisesRegex(MODULE.ModelIdentityError, "exactly one"):
                MODULE.verify_archive(duplicate, self.expected)


if __name__ == "__main__":
    unittest.main()
