from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location(
    "overlap_rescue_attribution",
    SCRIPT_DIR / "14_diagnose_overlap_rescue_attribution.py",
)
assert SPEC is not None and SPEC.loader is not None
diagnostic = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = diagnostic
SPEC.loader.exec_module(diagnostic)


class OverlapRescueAttributionTest(unittest.TestCase):
    def test_scale_invariant_sdr_is_invariant_to_gain_and_sign(self) -> None:
        reference = np.sin(np.linspace(0, 20, 32_000)).astype(np.float32)
        noisy = reference + np.cos(np.linspace(0, 31, 32_000)).astype(np.float32) * 0.1

        base = diagnostic.scale_invariant_sdr(noisy, reference)
        scaled = diagnostic.scale_invariant_sdr(noisy * -17.0, reference)

        self.assertIsNotNone(base)
        self.assertAlmostEqual(float(base), float(scaled), places=5)
        self.assertIsNone(diagnostic.scale_invariant_sdr(noisy, np.zeros_like(reference)))

    def test_common_gain_preserves_stream_energy_ratio(self) -> None:
        output = np.zeros((2, 32_000), dtype=np.float32)
        output[0] = np.sin(np.linspace(0, 30, 32_000)) * 10.0
        output[1] = np.cos(np.linspace(0, 30, 32_000)) * 2.0

        candidates, _ = diagnostic.common_gain_candidates(output, input_rms=0.05, available=32_000)

        before = diagnostic.root_mean_square(output[0]) / diagnostic.root_mean_square(output[1])
        after = diagnostic.root_mean_square(candidates[0]) / diagnostic.root_mean_square(candidates[1])
        reconstructed = candidates[0] + candidates[1]
        self.assertAlmostEqual(before, after, places=6)
        self.assertAlmostEqual(diagnostic.root_mean_square(reconstructed), 0.05, places=6)

    def test_oracle_uses_pit_instead_of_fixed_stream_order(self) -> None:
        target = np.sin(np.linspace(0, 20, 32_000)).astype(np.float32)
        other = np.cos(np.linspace(0, 31, 32_000)).astype(np.float32)
        candidates = [other + target * 0.01, target + other * 0.01]

        stream, target_scores, other_scores = diagnostic.oracle_target_stream(
            candidates, target, other, available=32_000
        )

        self.assertEqual(stream, 1)
        self.assertGreater(float(target_scores[1]), float(target_scores[0]))
        self.assertGreater(float(other_scores[0]), float(other_scores[1]))

    def test_reconstruct_trial_sources_matches_condition_truth(self) -> None:
        target = np.linspace(-0.1, 0.1, 32_000, dtype=np.float32)
        other = np.sin(np.linspace(0, 90, 20_000)).astype(np.float32) * 0.08

        mixture, target_source, other_source = diagnostic.reconstruct_trial_sources(
            {"condition": "overlap_sir_0db"}, target, other
        )

        np.testing.assert_allclose(mixture, target_source + other_source, rtol=1e-6, atol=1e-7)
        target_rms = diagnostic.root_mean_square(target_source)
        other_rms = diagnostic.root_mean_square(other_source)
        self.assertAlmostEqual(target_rms / other_rms, 1.0, places=5)

    def test_other_only_metrics_separates_gain_sensitive_leakage(self) -> None:
        rows = [
            {
                "split": "test",
                "condition": "other_only",
                "selected": [1],
                "current_false_rescue": True,
                "common_gain_false_rescue": False,
                "target_speaker": "target",
                "other_speaker": "other",
                "other_recording_id": "other-1",
                "current_text": "你好",
                "common_gain_text": "",
                "blocks": [
                    {
                        "selected": 1,
                        "selected_per_stream_rms_boost": 8.0,
                        "selected_common_rms_ratio": 0.125,
                        "selected_score": 0.31,
                        "raw_input_score": 0.22,
                        "selected_is_energy_dominant": False,
                    }
                ],
            }
        ]

        metrics = diagnostic.other_only_metrics(rows, "test")

        self.assertEqual(metrics["current_false_rescues"], 1)
        self.assertEqual(metrics["common_gain_false_rescues"], 0)
        self.assertEqual(metrics["false_rescues_removed_by_preserving_energy"], 1)
        self.assertEqual(metrics["lower_energy_selected_blocks"], 1)
        self.assertEqual(metrics["raw_input_already_above_threshold_blocks"], 0)
        self.assertEqual(metrics["separator_raised_above_threshold_blocks"], 1)


if __name__ == "__main__":
    unittest.main()
