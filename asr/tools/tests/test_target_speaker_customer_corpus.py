from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest
import wave


CORPUS = Path(__file__).parents[2] / "test-fixtures" / "target-speaker-customer-cases"


class TargetSpeakerCustomerCorpusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))

    def test_manifest_has_three_enrollment_and_three_customer_cases(self) -> None:
        files = self.manifest["files"]
        self.assertEqual(3, sum(item["role"] == "enrollment" for item in files))
        self.assertEqual(
            ["C1", "C2", "C3"],
            [item["case_id"] for item in files if item["role"] == "case"],
        )
        self.assertEqual("上海", self.manifest["business_assertion"]["required_text"])
        self.assertEqual("你好", self.manifest["business_assertion"]["forbidden_text"])

    def test_every_fixed_input_matches_its_sha256(self) -> None:
        for item in self.manifest["files"]:
            with self.subTest(path=item["path"]):
                path = CORPUS / item["path"]
                self.assertTrue(path.is_file())
                self.assertEqual(item["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_wavs_are_exact_16khz_mono_pcm16_inputs(self) -> None:
        for item in self.manifest["files"]:
            if item["role"] not in {"enrollment", "case"}:
                continue
            with self.subTest(path=item["path"]), wave.open(str(CORPUS / item["path"]), "rb") as wav:
                self.assertEqual("NONE", wav.getcomptype())
                self.assertEqual(item["sample_rate"], wav.getframerate())
                self.assertEqual(item["channels"], wav.getnchannels())
                self.assertEqual(item["sample_width_bytes"], wav.getsampwidth())
                self.assertEqual(item["frames"], wav.getnframes())
                self.assertAlmostEqual(
                    item["duration_seconds"],
                    wav.getnframes() / wav.getframerate(),
                    places=6,
                )


if __name__ == "__main__":
    unittest.main()
