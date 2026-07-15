from __future__ import annotations

import importlib.util
from array import array
from pathlib import Path
import sys
import tempfile
import unittest
import wave


SCRIPT = Path(__file__).with_name("run_device_stress.py")
SPEC = importlib.util.spec_from_file_location("run_device_stress", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RunCommandTest(unittest.TestCase):
    def test_invalid_utf8_from_hdc_is_replaced(self) -> None:
        result = MODULE.run(
            [sys.executable, "-c", "import os; os.write(1, b'valid\\xfftail')"]
        )

        self.assertEqual("valid\ufffdtail", result.stdout)

    def test_initial_signal_level_uses_only_requested_onset_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "onset.wav"
            with wave.open(str(path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16_000)
                wav.writeframes(array("h", [16_384] * 16_000 + [0] * 16_000).tobytes())
            source = MODULE.AudioSource(path, 16_000, 1, 2, 32_000, 2.0)

            first_second = MODULE.initial_signal_level(source, seconds=1.0)
            full_file = MODULE.initial_signal_level(source, seconds=2.0)

            self.assertAlmostEqual(0.5, first_second, places=3)
            self.assertAlmostEqual(0.5 / 2**0.5, full_file, places=3)


if __name__ == "__main__":
    unittest.main()
