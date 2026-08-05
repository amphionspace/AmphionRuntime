from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location(
    "overlap_rescue_synthetic", SCRIPT_DIR / "13_eval_overlap_rescue_synthetic.py"
)
assert SPEC is not None and SPEC.loader is not None
evaluation = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = evaluation
SPEC.loader.exec_module(evaluation)


class OverlapRescueSyntheticTest(unittest.TestCase):
    def test_mix_at_sir_preserves_shape_and_ratio(self) -> None:
        target = np.linspace(-0.04, 0.04, 32_000, dtype=np.float32)
        other = (np.sin(np.linspace(0, 100, 16_000)) * 0.03).astype(np.float32)

        mixed = evaluation.mix_at_sir(target, other, 5.0)

        target_rms = np.sqrt(np.mean(target.astype(np.float64) ** 2))
        other_component = mixed - target
        other_rms = np.sqrt(np.mean(other_component.astype(np.float64) ** 2))
        self.assertEqual(mixed.shape, target.shape)
        self.assertTrue(np.isfinite(mixed).all())
        self.assertAlmostEqual(20 * np.log10(target_rms / other_rms), 5.0, places=4)

    def test_mix_sources_at_sir_returns_exact_additive_components(self) -> None:
        target = np.linspace(-0.4, 0.4, 32_000, dtype=np.float32)
        other = np.cos(np.linspace(0, 60, 12_000)).astype(np.float32) * 0.3

        mixed, target_component, other_component = evaluation.mix_sources_at_sir(
            target, other, -5.0
        )

        np.testing.assert_allclose(mixed, target_component + other_component, rtol=1e-6, atol=1e-7)
        np.testing.assert_array_equal(mixed, evaluation.mix_at_sir(target, other, -5.0))
        self.assertLessEqual(float(np.max(np.abs(mixed))), 0.99)
        target_rms = np.sqrt(np.mean(target_component.astype(np.float64) ** 2))
        other_rms = np.sqrt(np.mean(other_component.astype(np.float64) ** 2))
        self.assertAlmostEqual(20 * np.log10(target_rms / other_rms), -5.0, places=4)

    def test_speaker_pairing_is_bijective_and_never_self(self) -> None:
        rows = []
        for speaker in ("a", "b", "c", "d"):
            rows.append(
                {
                    "split": "test",
                    "condition": "clean",
                    "label": 1,
                    "target_speaker": speaker,
                    "probe_recording_id": f"{speaker}-1",
                }
            )

        pairs = evaluation.choose_speaker_pairs(rows, "test", None, seed=73)

        self.assertEqual(len(pairs), 4)
        self.assertEqual(len({other["target_speaker"] for _, other in pairs}), 4)
        self.assertTrue(all(left["target_speaker"] != right["target_speaker"] for left, right in pairs))

    def test_other_attribution_removes_target_explainable_characters(self) -> None:
        attributed = evaluation.attributed_other_characters(
            "准备去上海", "你好", "准备去上海你好"
        )

        self.assertEqual(attributed, 2)

    def test_trial_metrics_reports_false_rescue_and_rejection(self) -> None:
        rows = [
            {
                "split": "test",
                "condition": "other_only",
                "target_reference_text": "",
                "other_reference_text": "你好",
                "raw_text": "你好",
                "rescued_text": "你",
                "selected": [0],
            },
            {
                "split": "test",
                "condition": "target_only",
                "target_reference_text": "上海",
                "other_reference_text": "",
                "raw_text": "上海",
                "rescued_text": "",
                "selected": [-1],
            },
        ]

        other = evaluation.trial_metrics(rows, "test", "other_only")
        target = evaluation.trial_metrics(rows, "test", "target_only")

        self.assertEqual(other["false_rescues"], 1)
        self.assertEqual(target["false_rejections"], 1)
        self.assertEqual(target["rescued_target_cer"], 1.0)

    def test_selected_silent_other_is_not_counted_as_textual_false_rescue(self) -> None:
        rows = [
            {
                "split": "test",
                "condition": "other_only",
                "target_reference_text": "",
                "other_reference_text": "你好",
                "raw_text": "你好",
                "rescued_text": "",
                "selected": [0, -1],
            }
        ]

        metrics = evaluation.trial_metrics(rows, "test", "other_only")

        self.assertEqual(metrics["selection_accept_trials"], 1)
        self.assertEqual(metrics["nonempty_output_trials"], 0)
        self.assertEqual(metrics["false_rescues"], 0)


if __name__ == "__main__":
    unittest.main()
