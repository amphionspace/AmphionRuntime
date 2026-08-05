from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location(
    "c1_turn_transition_synthetic",
    SCRIPT_DIR / "15_eval_c1_turn_transition_synthetic.py",
)
assert SPEC is not None and SPEC.loader is not None
evaluation = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = evaluation
SPEC.loader.exec_module(evaluation)


class C1TurnTransitionSyntheticTest(unittest.TestCase):
    def test_compose_transition_places_gap_and_overlap_on_one_timeline(self) -> None:
        target = np.ones(32_000, dtype=np.float32) * 0.1
        other = np.ones(16_000, dtype=np.float32) * 0.2

        gapped, gap = evaluation.compose_transition(
            target, other, gap_sec=0.3, other_tail_sec=0.6
        )
        overlapped, overlap = evaluation.compose_transition(
            target, other, gap_sec=-0.3, other_tail_sec=0.6
        )

        self.assertEqual(gap["other_start_sample"], 36_800)
        self.assertTrue(np.all(gapped[32_000:36_800] == 0))
        self.assertEqual(overlap["other_start_sample"], 27_200)
        self.assertTrue(np.allclose(overlapped[27_200:32_000], 0.3))

    def test_partition_sizes_preserve_every_sample(self) -> None:
        total = 52_317

        for pattern in ("realtime_20ms", "irregular", "single_block"):
            parts = evaluation.partition_sizes(total, pattern)
            self.assertEqual(sum(parts), total)
            self.assertTrue(all(value > 0 for value in parts))

    def test_target_duration_buckets_are_explicit_at_boundaries(self) -> None:
        self.assertEqual(evaluation.target_duration_bucket(2.499), "short_lt_2.5s")
        self.assertEqual(evaluation.target_duration_bucket(2.5), "medium_2.5_to_4s")
        self.assertEqual(evaluation.target_duration_bucket(4.0), "long_ge_4s")

    def test_legacy_score_schedule_preserves_one_score_per_call_semantics(self) -> None:
        session = np.ones(32_000, dtype=np.float32)

        realtime = evaluation.build_sdk_timeline(
            session,
            chunk_pattern="realtime_20ms",
            score_schedule="legacy_per_call",
            target_end_sample=16_000,
            other_start_sample=16_000,
            score_window=lambda window: float(np.mean(window)),
        )
        single = evaluation.build_sdk_timeline(
            session,
            chunk_pattern="single_block",
            score_schedule="legacy_per_call",
            target_end_sample=16_000,
            other_start_sample=16_000,
            score_window=lambda window: float(np.mean(window)),
        )

        self.assertEqual([round(point.time_sec, 1) for point in realtime], [1.0, 1.2, 1.5, 1.8])
        self.assertEqual([point.time_sec for point in single], [2.0])

    def test_absolute_score_schedule_is_independent_of_caller_partitioning(self) -> None:
        session = np.arange(32_000, dtype=np.float32)

        def score_times(pattern: str) -> list[float]:
            points = evaluation.build_sdk_timeline(
                session,
                chunk_pattern=pattern,
                score_schedule="absolute_samples",
                target_end_sample=16_000,
                other_start_sample=16_000,
                score_window=lambda window: float(window[-1]),
            )
            return [point.time_sec for point in points]

        expected = [1.0, 1.2, 1.5, 1.8]
        self.assertEqual(score_times("realtime_20ms"), expected)
        self.assertEqual(score_times("irregular"), expected)
        self.assertEqual(score_times("single_block"), expected)

    def test_legacy_large_block_can_change_two_phase_decision(self) -> None:
        session = np.concatenate(
            [np.ones(19_200, dtype=np.float32), np.zeros(25_600, dtype=np.float32)]
        )

        def result(pattern: str):
            points = evaluation.build_sdk_timeline(
                session,
                chunk_pattern=pattern,
                score_schedule="legacy_per_call",
                target_end_sample=19_200,
                other_start_sample=19_200,
                score_window=lambda window: float(np.mean(window)),
            )
            return evaluation.speaker_vad.simulate(
                points,
                threshold=0.35,
                consecutive_below=2,
                total_sec=len(session) / 16_000,
            )

        realtime = result("realtime_20ms")
        single = result("single_block")

        self.assertEqual(realtime.state, "endpoint")
        self.assertEqual(single.state, "target_not_confirmed")

    def test_asr_metrics_counts_rejected_target_and_other_leakage(self) -> None:
        rows = [
            {
                "target_reference_text": "准备去上海",
                "other_reference_text": "你好",
                "target_only_text": "准备去上海",
                "baseline_text": "准备去上海你好",
                "published_text": "",
            },
            {
                "target_reference_text": "打开空调",
                "other_reference_text": "二十一度",
                "target_only_text": "打开空调",
                "baseline_text": "打开空调二十一度",
                "published_text": "打开空调二十一度",
            },
        ]

        metrics = evaluation.asr_metrics(rows)

        self.assertEqual(metrics["published_empty_trials"], 1)
        self.assertEqual(metrics["published_other_text_trials"], 1)
        self.assertEqual(metrics["target_regression_trials"], 2)

    def test_buffered_commit_rolls_endpoint_back_by_the_frozen_tail(self) -> None:
        result = evaluation.speaker_vad.SimResult(
            state="endpoint",
            endpoint_sec=2.4,
            target_confirm_sec=1.0,
            below_count=2,
        )

        decision = evaluation.buffered_commit_decision(result, total_samples=48_000)

        self.assertEqual(decision.publish_samples, 28_800)
        self.assertEqual(decision.rollback_samples, 9_600)
        self.assertEqual(decision.reason, "confirmed_departure")

    def test_buffered_commit_flushes_continuous_target_on_finish(self) -> None:
        result = evaluation.speaker_vad.SimResult(
            state="target_confirmed_no_endpoint",
            endpoint_sec=3.0,
            target_confirm_sec=1.0,
            below_count=0,
        )

        decision = evaluation.buffered_commit_decision(result, total_samples=48_000)

        self.assertEqual(decision.publish_samples, 48_000)
        self.assertEqual(decision.rollback_samples, 0)
        self.assertEqual(decision.reason, "clean_finish")

    def test_buffered_commit_discards_unresolved_low_tail_on_finish(self) -> None:
        result = evaluation.speaker_vad.SimResult(
            state="target_confirmed_no_endpoint",
            endpoint_sec=3.0,
            target_confirm_sec=1.0,
            below_count=1,
        )

        decision = evaluation.buffered_commit_decision(result, total_samples=48_000)

        self.assertEqual(decision.publish_samples, 38_400)
        self.assertEqual(decision.rollback_samples, 9_600)
        self.assertEqual(decision.reason, "unresolved_departure_at_finish")

    def test_buffered_commit_rejects_segment_without_target_confirmation(self) -> None:
        result = evaluation.speaker_vad.SimResult(
            state="pre_target_endpoint",
            endpoint_sec=1.2,
            target_confirm_sec=None,
            below_count=2,
        )

        decision = evaluation.buffered_commit_decision(result, total_samples=32_000)

        self.assertEqual(decision.publish_samples, 0)
        self.assertEqual(decision.reason, "target_not_confirmed")

    def test_direct_publication_policy_preserves_the_detected_endpoint(self) -> None:
        result = evaluation.speaker_vad.SimResult(
            state="endpoint",
            endpoint_sec=2.4,
            target_confirm_sec=1.0,
            below_count=2,
        )

        decision = evaluation.publication_decision(
            result,
            total_samples=48_000,
            policy="direct_endpoint",
        )

        self.assertEqual(decision.publish_samples, 38_400)
        self.assertEqual(decision.rollback_samples, 0)


if __name__ == "__main__":
    unittest.main()
