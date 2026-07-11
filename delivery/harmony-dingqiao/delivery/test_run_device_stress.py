from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


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


if __name__ == "__main__":
    unittest.main()
