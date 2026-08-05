from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location(
    "convtasnet_frontend", SCRIPT_DIR / "10_eval_convtasnet_frontend.py"
)
assert SPEC is not None and SPEC.loader is not None
frontend = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = frontend
SPEC.loader.exec_module(frontend)


class FakeStream:
    def __init__(self) -> None:
        self.samples = np.zeros(0, dtype=np.float32)

    def accept_waveform(self, *, sample_rate: int, waveform: np.ndarray) -> None:
        self.samples = waveform

    def input_finished(self) -> None:
        pass


class FakeExtractor:
    def create_stream(self) -> FakeStream:
        return FakeStream()

    def is_ready(self, stream: FakeStream) -> bool:
        return bool(len(stream.samples))

    def compute(self, stream: FakeStream) -> np.ndarray:
        return np.asarray([float(np.mean(stream.samples)), 1.0], dtype=np.float32)


class ConvTasNetFrontendTest(unittest.TestCase):
    def test_output_directory_must_not_overwrite_prior_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result"
            output.mkdir()
            marker = output / "summary.json"
            marker.write_text("prior-result", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                frontend.prepare_output_dir(output)

            self.assertEqual(marker.read_text(encoding="utf-8"), "prior-result")

    def test_output_directory_allows_new_or_empty_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result"

            frontend.prepare_output_dir(output)
            frontend.prepare_output_dir(output)

            self.assertTrue(output.is_dir())

    def test_resample_round_trip_preserves_expected_length_and_finiteness(self) -> None:
        samples = np.linspace(-0.5, 0.5, 16_001, dtype=np.float32)

        down = frontend.resample_audio(samples, 16_000, 8_000)
        restored = frontend.resample_audio(down, 8_000, 16_000)

        self.assertEqual(len(down), 8_001)
        self.assertEqual(len(restored), 16_002)
        self.assertTrue(np.isfinite(restored).all())

    def test_window_embedding_count_matches_baseline_complete_windows(self) -> None:
        samples = np.ones(64_000, dtype=np.float32)

        embeddings = frontend.extract_window_embeddings(
            FakeExtractor(),
            samples,
            win_sec=2.5,
            hop_sec=1.0,
            min_duration_sec=1.5,
        )

        self.assertEqual(len(embeddings), 2)
        self.assertTrue(all(np.isclose(np.linalg.norm(item), 1.0) for item in embeddings))

    def test_max_source_selection_applies_to_any_label(self) -> None:
        target = np.asarray([1.0, 0.0], dtype=np.float32)
        sources = [
            [np.asarray([0.2, 0.98], dtype=np.float32)],
            [np.asarray([0.8, 0.6], dtype=np.float32)],
        ]

        score, selected, source_scores = frontend.score_separated_sources(sources, target)

        self.assertAlmostEqual(score, 0.8)
        self.assertEqual(selected, 1)
        np.testing.assert_allclose(source_scores, [0.2, 0.8])

    def test_metrics_group_test_conditions_only(self) -> None:
        rows = [
            {"split": "dev", "condition": "clean", "label": 1, "score": 0.1},
            {"split": "test", "condition": "clean", "label": 1, "score": 0.9},
            {"split": "test", "condition": "clean", "label": 0, "score": 0.2},
            {"split": "test", "condition": "traffic_snr_0db", "label": 1, "score": 0.4},
            {"split": "test", "condition": "traffic_snr_0db", "label": 0, "score": 0.6},
        ]

        metrics = frontend.metrics_by_condition(rows, "score", 0.5)

        self.assertEqual(metrics["clean"]["false_accepts"], 0)
        self.assertEqual(metrics["clean"]["false_rejects"], 0)
        self.assertEqual(metrics["traffic_snr_0db"]["false_accepts"], 1)
        self.assertEqual(metrics["traffic_snr_0db"]["false_rejects"], 1)

    def test_probe_loader_does_not_resample_already_normalized_audio_twice(self) -> None:
        normalized = np.linspace(-0.5, 0.5, 16_000, dtype=np.float32)
        row = {
            "probe_audio_path": "source-48k.wav",
            "noise_audio_path": None,
            "snr_db": None,
        }

        with mock.patch.object(
            frontend, "load_audio_mono16k", return_value=(normalized, 48_000)
        ):
            loaded = frontend.load_probe_audio(row)

        np.testing.assert_array_equal(loaded, normalized)

    def test_far_constrained_threshold_preserves_limit_before_minimizing_frr(self) -> None:
        selected = frontend.select_far_constrained_threshold(
            [0.9, 0.7, 0.6, 0.5],
            [1, 1, 0, 0],
            max_far=0.0,
        )

        self.assertEqual(selected["far"], 0.0)
        self.assertEqual(selected["frr"], 0.0)
        self.assertAlmostEqual(selected["threshold"], 0.65)


if __name__ == "__main__":
    unittest.main()
