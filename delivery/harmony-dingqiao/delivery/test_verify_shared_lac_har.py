"""Exercise the HAR asset verifier with the same split LAC inputs as Hvigor."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPT = SCRIPT_DIR / "verify_selfcontained_dingqiao_har.sh"


class SharedLacHarVerificationTest(unittest.TestCase):
    def verify(self, *, zh_only: bool, shared_bytes=b"lac model", packaged_bytes=b"lac model"):
        # Execute the real embedded verifier without invoking the device/build toolchain.
        source = SCRIPT.read_text()
        start = source.index("import sys\nimport tarfile\n")
        program = source[start:source.index("\nPY\n", start)]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"bundles": {"zh-en/v1": []}}))
            local = [root / name for name in ("voiceprint", "segmentation", "capi", "ort", "agc")]
            for path in local:
                path.write_bytes(path.name.encode())
            police = root / "police"
            (police / "lac/v1").mkdir(parents=True)
            shared = root / "shared-lac.onnx"
            if shared_bytes is not None:
                shared.write_bytes(shared_bytes)
            # The encoder is intentionally absent from the source police tree.
            police_manifest = {"files": {"lac/v1/lac_encoder.onnx": hashlib.sha256(b"lac model").hexdigest()}}
            (police / "manifest.json").write_text(json.dumps(police_manifest, indent=2) + "\n")
            entries = {
                "package/oh-package.json5": json.dumps({"dependencies": {"amphion_police": "file:./_bundled/amphion_police"}}).encode(),
                "package/_bundled/amphion_police/oh-package.json5": json.dumps({"dependencies": {"amphion_asr": "file:../amphion_asr"}}).encode(),
                "package/_bundled/amphion_asr/src/main/resources/rawfile/amphion-models/manifest.json": manifest.read_bytes(),
                "package/src/main/resources/rawfile/amphion-dingqiao/eres2net.onnx": local[0].read_bytes(),
                "package/src/main/resources/rawfile/amphion-dingqiao/pyannote-segmentation-3.0.onnx": local[1].read_bytes(),
            }
            for module in ("amphion_asr", "sherpa_onnx"):
                for name, path in (("libsherpa-onnx-c-api.so", local[2]), ("libonnxruntime.so", local[3])):
                    entries[f"package/_bundled/{module}/libs/arm64-v8a/{name}"] = path.read_bytes()
            entries["package/_bundled/amphion_asr/libs/arm64-v8a/libamphion_audio_processing.so"] = local[4].read_bytes()
            prefix = "package/_bundled/amphion_police/src/main/resources/rawfile/amphion-police/"
            entries[prefix + "manifest.json"] = (police / "manifest.json").read_bytes()
            entries[prefix + "lac/v1/lac_encoder.onnx"] = packaged_bytes
            har = root / "sdk.har"
            with tarfile.open(har, "w:gz") as archive:
                for name, data in entries.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
            return subprocess.run(
                [sys.executable, "-", str(har), str(manifest), *map(str, local),
                 str(police), str(zh_only).lower(), "", str(SCRIPT_DIR), str(shared)],
                input=program, text=True, capture_output=True,
            )

    def test_shared_model_verifies_with_source_only_police_assets(self):
        for zh_only in (False, True):
            with self.subTest(zh_only=zh_only):
                result = self.verify(zh_only=zh_only)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_missing_shared_model_is_rejected(self):
        result = self.verify(zh_only=True, shared_bytes=None)
        self.assertNotEqual(0, result.returncode)

    def test_different_model_in_har_is_rejected(self):
        for zh_only in (False, True):
            with self.subTest(zh_only=zh_only):
                result = self.verify(zh_only=zh_only, packaged_bytes=b"wrong model")
                self.assertNotEqual(0, result.returncode)
                self.assertIn("lac/v1/lac_encoder.onnx", result.stderr)


if __name__ == "__main__":
    unittest.main()
