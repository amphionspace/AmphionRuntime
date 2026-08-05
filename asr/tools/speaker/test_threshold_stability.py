from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location(
    "threshold_stability", SCRIPT_DIR / "09_eval_threshold_stability.py"
)
assert SPEC is not None and SPEC.loader is not None
stability = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = stability
SPEC.loader.exec_module(stability)


class ThresholdStabilityTest(unittest.TestCase):
    def test_bootstrap_is_deterministic_and_clustered(self) -> None:
        dev_rows = []
        for speaker, positive, negative in (
            ("a", 0.9, 0.1),
            ("b", 0.8, 0.2),
            ("c", 0.7, 0.3),
        ):
            dev_rows.extend([
                {"target_speaker": speaker, "score": positive, "label": 1},
                {"target_speaker": speaker, "score": negative, "label": 0},
            ])
        test_rows = [
            {"score": 0.85, "label": 1},
            {"score": 0.75, "label": 1},
            {"score": 0.25, "label": 0},
            {"score": 0.15, "label": 0},
        ]

        first = stability.bootstrap_thresholds(
            dev_rows, test_rows, iterations=20, seed=7, far_limit=0.05
        )
        second = stability.bootstrap_thresholds(
            dev_rows, test_rows, iterations=20, seed=7, far_limit=0.05
        )

        self.assertEqual(first, second)
        self.assertEqual(first["dev_speaker_clusters"], 3)
        self.assertLessEqual(first["threshold"]["p05"], first["threshold"]["p95"])


if __name__ == "__main__":
    unittest.main()
