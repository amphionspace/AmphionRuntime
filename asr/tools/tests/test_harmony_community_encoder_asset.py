from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
MODEL = ROOT / "shared/models/asr/dingqiao/community-wespeaker-encoder.int8.onnx"
MANIFEST = ROOT / "delivery/harmony-dingqiao/delivery/community_diarization_1.json"
QUANTIZER = ROOT / "asr/tools/quantize_community_encoder.py"
NATIVE = ROOT / "asr/harmony/sdk/src/main/cpp/community_diarization.cpp"
HVIGOR = ROOT / "asr/harmony/sdk-dingqiao/hvigorfile.ts"
IDENTITY = ROOT / "delivery/harmony-dingqiao/delivery/harmony_build_identity.py"

SPEC = importlib.util.spec_from_file_location("quantize_community_encoder", QUANTIZER)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HarmonyCommunityEncoderAssetTest(unittest.TestCase):
    def test_pinned_int8_asset_matches_manifest(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        entry = next(item for item in manifest["files"] if item["file"] == MODEL.name)
        self.assertEqual(entry["sizeBytes"], MODEL.stat().st_size)
        self.assertEqual(entry["sha256"], hashlib.sha256(MODEL.read_bytes()).hexdigest())
        self.assertTrue(entry["quantization"]["perChannel"])
        self.assertEqual("harmony", entry["runtime"])

    def test_split_export_inputs_remain_the_first_two_manifest_entries(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(
            [
                "community-wespeaker-encoder.fp32.onnx",
                "community-wespeaker-pool.fp32.onnx",
            ],
            [entry["file"] for entry in manifest["files"][:2]],
        )

    def test_harmony_load_build_and_identity_use_only_the_int8_encoder(self) -> None:
        for path in (NATIVE, HVIGOR, IDENTITY):
            source = path.read_text(encoding="utf-8")
            self.assertIn(MODEL.name, source, path)
        self.assertNotIn("community-wespeaker-encoder.fp32.onnx", NATIVE.read_text())
        self.assertIn("oldFp32Encoder", HVIGOR.read_text())

    def test_calibration_contract_rejects_gaps_and_hashes_in_numeric_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(MODULE.EXPECTED_CALIBRATION_WINDOWS):
                (root / f"cal_{index}.f32").write_bytes(bytes([index]) * MODULE.FBANK_BYTES)
            paths = MODULE.calibration_files(root)
            self.assertEqual("cal_2.f32", paths[2].name)
            first = MODULE.calibration_digest(paths)
            (root / "cal_2.f32").write_bytes(b"x" * MODULE.FBANK_BYTES)
            self.assertNotEqual(first, MODULE.calibration_digest(paths))
            (root / "cal_2.f32").unlink()
            with self.assertRaisesRegex(MODULE.QuantizationInputError, "expected 21"):
                MODULE.calibration_files(root)


if __name__ == "__main__":
    unittest.main()
