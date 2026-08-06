from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("verify_target_speaker_model.py")
SPEC = importlib.util.spec_from_file_location("verify_target_speaker_model", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class VerifyTargetSpeakerModelTest(unittest.TestCase):
    def test_accepts_pinned_harmony_ort_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "convtasnet_16k.ort"
            model.write_bytes(b"ort-model")
            metadata = root / "metadata.json"
            metadata.write_text(
                json.dumps(
                    {
                        "format": "ort",
                        "converter_id": MODULE.EXPECTED_CONVERTER,
                        "output_size_bytes": model.stat().st_size,
                        "output_sha256": MODULE.sha256_file(model),
                    }
                ),
                encoding="utf-8",
            )
            MODULE.verify(model, metadata)

    def test_rejects_changed_model_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "convtasnet_16k.ort"
            model.write_bytes(b"changed")
            metadata = root / "metadata.json"
            metadata.write_text(
                json.dumps(
                    {
                        "format": "ort",
                        "converter_id": MODULE.EXPECTED_CONVERTER,
                        "output_size_bytes": model.stat().st_size,
                        "output_sha256": "0" * 64,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                MODULE.verify(model, metadata)


if __name__ == "__main__":
    unittest.main()
