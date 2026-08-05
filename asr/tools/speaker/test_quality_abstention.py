from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location(
    "quality_abstention", SCRIPT_DIR / "08_eval_quality_abstention.py"
)
assert SPEC is not None and SPEC.loader is not None
quality = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = quality
SPEC.loader.exec_module(quality)


class QualityAbstentionTest(unittest.TestCase):
    def test_audio_quality_features_are_finite(self) -> None:
        samples = np.sin(np.linspace(0.0, 100.0, 32000)).astype(np.float32) * 0.1

        features = quality.audio_quality_features(samples)

        self.assertEqual(set(features), set(quality.QUALITY_FEATURES) - set(quality.SCORE_FEATURES))
        self.assertTrue(all(np.isfinite(value) for value in features.values()))
        self.assertAlmostEqual(features["duration_sec"], 2.0)

    def test_error_ranker_orders_separable_errors(self) -> None:
        matrix = np.asarray([[-2.0], [-1.0], [1.0], [2.0]])
        labels = np.asarray([0.0, 0.0, 1.0, 1.0])

        model = quality.fit_error_ranker(matrix, labels)
        risks = quality.predict_error_risk(model, matrix)

        self.assertLess(float(np.max(risks[:2])), float(np.min(risks[2:])))

    def test_abstain_threshold_never_exceeds_budget_at_ties(self) -> None:
        risks = np.asarray([0.9, 0.8, 0.8, 0.1])

        threshold = quality.select_abstain_threshold(risks, 0.5)

        self.assertEqual(threshold, 0.9)
        self.assertLessEqual(int(np.sum(risks >= threshold)), 2)

    def test_ranking_metrics_separate_good_and_bad_rankings(self) -> None:
        labels = [1.0, 1.0, 0.0, 0.0]

        good = quality.ranking_metrics([0.9, 0.8, 0.2, 0.1], labels)
        bad = quality.ranking_metrics([0.1, 0.2, 0.8, 0.9], labels)

        self.assertEqual(good["roc_auc"], 1.0)
        self.assertEqual(good["average_precision"], 1.0)
        self.assertEqual(bad["roc_auc"], 0.0)

    def test_policy_reports_coverage_and_captured_errors(self) -> None:
        rows = [
            {"label": 1, "score": 0.4, "condition": "clean"},
            {"label": 1, "score": 0.8, "condition": "clean"},
            {"label": 0, "score": 0.2, "condition": "clean"},
            {"label": 0, "score": 0.7, "condition": "clean"},
        ]
        risks = np.asarray([0.9, 0.1, 0.2, 0.8])

        result = quality.evaluate_policy(rows, risks, 0.85, 0.5)["all"]

        self.assertEqual(result["abstained"], 1)
        self.assertEqual(result["errors_abstained"], 1)
        self.assertEqual(result["coverage"], 0.75)
        self.assertEqual(result["conditional_frr"], 0.0)
        self.assertEqual(result["conditional_far"], 0.5)


if __name__ == "__main__":
    unittest.main()
