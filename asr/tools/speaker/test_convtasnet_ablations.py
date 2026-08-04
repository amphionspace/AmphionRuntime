from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location(
    "convtasnet_ablations", SCRIPT_DIR / "11_eval_convtasnet_ablations.py"
)
assert SPEC is not None and SPEC.loader is not None
ablation = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ablation
SPEC.loader.exec_module(ablation)


class ConvTasNetAblationTest(unittest.TestCase):
    def test_existing_result_must_link_to_exact_baseline_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary_path = root / "summary.json"
            trials_path = root / "trials.jsonl"
            summary_path.write_text("{}", encoding="utf-8")
            trials_path.write_text(json.dumps({"trial": 1}) + "\n", encoding="utf-8")
            linked = {
                "artifacts": {
                    "baseline_summary_sha256": ablation.frontend.sha256(summary_path),
                    "baseline_trials_sha256": ablation.frontend.sha256(trials_path),
                }
            }

            ablation.verify_existing_baseline_linkage(linked, summary_path, trials_path)
            trials_path.write_text(json.dumps({"trial": 2}) + "\n", encoding="utf-8")

            with self.assertRaises(RuntimeError):
                ablation.verify_existing_baseline_linkage(
                    linked, summary_path, trials_path
                )

    def test_bandwidth_round_trip_preserves_input_length(self) -> None:
        samples = np.linspace(-0.2, 0.2, 16_001, dtype=np.float32)

        restored = ablation.bandwidth_round_trip(samples)

        self.assertEqual(restored.shape, samples.shape)
        self.assertTrue(np.isfinite(restored).all())

    def test_interferer_excludes_target_and_probe_speaker(self) -> None:
        row = {
            "split": "test",
            "target_speaker": "target",
            "probe_speaker": "probe",
            "probe_recording_id": "probe-1",
        }
        pool = [
            {"speaker": "target", "recording_id": "a", "audio_path": "a.wav"},
            {"speaker": "probe", "recording_id": "b", "audio_path": "b.wav"},
            {"speaker": "safe", "recording_id": "c", "audio_path": "c.wav"},
        ]

        selected = ablation.select_interferer(row, pool, seed=73)

        self.assertEqual(selected["speaker"], "safe")

    def test_overlap_rows_keep_one_positive_and_requested_negatives(self) -> None:
        rows = []
        for target in ("a", "b"):
            rows.append({"split": "test", "target_speaker": target, "label": 1})
            for index in range(3):
                rows.append(
                    {
                        "split": "test",
                        "target_speaker": target,
                        "probe_speaker": f"n{index}",
                        "probe_recording_id": f"r{index}",
                        "label": 0,
                    }
                )

        selected = ablation.select_overlap_rows(rows, negatives_per_target=1)

        self.assertEqual(len(selected), 4)
        self.assertEqual(sum(row["label"] == 1 for row in selected), 2)
        self.assertEqual(sum(row["label"] == 0 for row in selected), 2)

    def test_interferer_selection_is_deterministic(self) -> None:
        row = {
            "split": "dev",
            "target_speaker": "a",
            "probe_speaker": "a",
            "probe_recording_id": "r1",
        }
        pool = [
            {"speaker": name, "recording_id": name, "audio_path": f"{name}.wav"}
            for name in ("a", "b", "c", "d")
        ]

        first = ablation.select_interferer(row, pool, seed=73)
        second = ablation.select_interferer(row, pool, seed=73)

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
