from __future__ import annotations

import gzip
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

SPEC = importlib.util.spec_from_file_location(
    "voiceprint_pilot", SCRIPT_DIR / "07_eval_voiceprint_verification.py"
)
assert SPEC is not None and SPEC.loader is not None
pilot = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pilot
SPEC.loader.exec_module(pilot)

from ts_asr import core  # noqa: E402


class VoiceprintPilotTest(unittest.TestCase):
    def test_denoiser_scope_defaults_to_all_and_accepts_probe_only(self) -> None:
        required = [
            "voiceprint-pilot",
            "--cuts",
            "cuts.jsonl.gz",
            "--speaker-model",
            "speaker.onnx",
            "--out-dir",
            "results",
        ]
        with mock.patch.object(sys, "argv", required):
            args = pilot.parse_args()
            self.assertEqual(args.denoiser_scope, "all")
            self.assertEqual(args.enroll_utterances, 3)
        with mock.patch.object(sys, "argv", required + ["--denoiser-scope", "probe"]):
            self.assertEqual(pilot.parse_args().denoiser_scope, "probe")

    def test_dev_threshold_balances_far_and_frr(self) -> None:
        selected = pilot.select_eer_threshold(
            [0.9, 0.8, 0.4, 0.3],
            [1, 1, 0, 0],
        )

        self.assertAlmostEqual(selected["threshold"], 0.6)
        self.assertEqual(selected["far"], 0.0)
        self.assertEqual(selected["frr"], 0.0)

    def test_fixed_threshold_is_not_reselected_from_dev(self) -> None:
        operating, diagnostic = pilot.choose_operating_threshold(
            [0.9, 0.8, 0.4, 0.3],
            [1, 1, 0, 0],
            0.85,
        )

        self.assertEqual(operating["threshold"], 0.85)
        self.assertEqual(operating["source"], "cli_fixed")
        self.assertEqual(operating["frr"], 0.5)
        self.assertAlmostEqual(diagnostic["threshold"], 0.6)

    def test_binary_metrics_reports_wilson_intervals(self) -> None:
        metrics = pilot.binary_metrics([0.9, 0.8, 0.2], [1, 0, 0], threshold=0.5)

        self.assertEqual(metrics["false_accepts"], 1)
        self.assertEqual(metrics["false_rejects"], 0)
        self.assertEqual(len(metrics["far_wilson_95"]), 2)
        self.assertGreater(metrics["frr_wilson_95"][1], 0.0)

    def test_collect_speakers_requires_distinct_existing_recordings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio = root / "audio.wav"
            audio.write_bytes(b"placeholder")
            manifest = root / "cuts.jsonl.gz"
            rows = []
            for speaker in ("s1", "s2"):
                for index in range(2):
                    recording_id = f"{speaker}-{index}"
                    rows.append(
                        {
                            "id": recording_id,
                            "duration": 2.0,
                            "supervisions": [
                                {
                                    "speaker": speaker,
                                    "recording_id": recording_id,
                                    "text": "测试",
                                }
                            ],
                            "recording": {
                                "sources": [{"type": "file", "source": str(audio)}]
                            },
                        }
                    )
            with gzip.open(manifest, "wt", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")

            speakers, counters = pilot.collect_speakers(
                [manifest],
                required_utterances=2,
                required_speakers=2,
                min_duration_sec=1.5,
                max_duration_sec=10.0,
            )

        self.assertEqual(sorted(speakers), ["s1", "s2"])
        self.assertEqual(counters["rows_seen"], 4)

    def test_collect_speakers_can_scan_past_required_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio = root / "audio.wav"
            audio.write_bytes(b"placeholder")
            manifest = root / "cuts.jsonl.gz"
            rows = []
            for speaker in ("early", "late"):
                for index in range(2):
                    recording_id = f"{speaker}-{index}"
                    rows.append(
                        {
                            "id": recording_id,
                            "duration": 2.0,
                            "supervisions": [{"speaker": speaker, "recording_id": recording_id}],
                            "recording": {
                                "sources": [{"type": "file", "source": str(audio)}]
                            },
                        }
                    )
            with gzip.open(manifest, "wt", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")

            speakers, counters = pilot.collect_speakers(
                [manifest],
                required_utterances=2,
                required_speakers=1,
                min_duration_sec=1.5,
                max_duration_sec=10.0,
                stop_when_ready=False,
            )

        self.assertEqual(sorted(speakers), ["early", "late"])
        self.assertEqual(counters["rows_seen"], 4)

    def test_arrange_session_disjoint_uses_different_sessions(self) -> None:
        rows = [
            pilot.Utterance(f"s-a-{index}", "s", Path("a.wav"), 2.0, "", "a")
            for index in range(3)
        ] + [
            pilot.Utterance(f"s-b-{index}", "s", Path("b.wav"), 2.0, "", "b")
            for index in range(2)
        ]

        selected = pilot.arrange_session_disjoint(
            rows,
            enroll_utterances=2,
            probe_start=2,
            target_probes=2,
        )

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual({row.session_id for row in selected[:2]}, {"a"})
        self.assertEqual({row.session_id for row in selected[2:]}, {"b"})

    def test_collect_speakers_extracts_session_from_recording_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio = root / "audio.wav"
            audio.write_bytes(b"placeholder")
            manifest = root / "cuts.jsonl.gz"
            with gzip.open(manifest, "wt", encoding="utf-8") as handle:
                for session in ("c1", "c2"):
                    for index in range(2):
                        recording_id = f"s-{session}-{index}"
                        handle.write(json.dumps({
                            "id": recording_id,
                            "duration": 2.0,
                            "supervisions": [{"speaker": "s", "recording_id": recording_id}],
                            "recording": {"sources": [{"type": "file", "source": str(audio)}]},
                        }) + "\n")

            speakers, _ = pilot.collect_speakers(
                [manifest],
                required_utterances=4,
                required_speakers=1,
                min_duration_sec=1.5,
                max_duration_sec=10.0,
                session_id_regex=r"^s-(?P<session>c\d)-",
                enroll_utterances=2,
                probe_start=2,
                target_probes=2,
            )

        self.assertEqual([row.session_id for row in speakers["s"]], ["c1", "c1", "c2", "c2"])

    def test_report_describes_session_proxy_without_overclaiming(self) -> None:
        summary = {
            "corpus": "example",
            "config": {
                "dev_speakers": 1,
                "test_speakers": 1,
                "enroll_utterances": 2,
                "session_id_regex": "(?P<session>.+)",
            },
            "dev_diagnostic_eer": {"eer_approx": 0.0},
            "dev_threshold": {"threshold": 0.5, "source": "dev_eer"},
            "test_at_dev_threshold": {
                "far": 0.0,
                "frr": 0.0,
                "false_accepts": 0,
                "false_rejects": 0,
                "negative_trials": 1,
                "positive_trials": 1,
                "far_wilson_95": [0.0, 0.8],
                "frr_wilson_95": [0.0, 0.8],
            },
            "test_diagnostic_eer": {"eer_approx": 0.0},
        }

        report = pilot.render_report(summary)

        self.assertIn("enrollment/probe 强制不相交", report)
        self.assertIn("不等同于已验证的录制日期", report)

    def test_asr_metrics_counts_rejected_target_as_full_error(self) -> None:
        rows = [
            {"label": 1, "score": 0.4, "reference_text": "你好", "asr_text": "你好"},
            {"label": 0, "score": 0.6, "reference_text": "别人", "asr_text": "别人说话"},
        ]

        metrics = pilot.asr_metrics(rows, threshold=0.5)

        self.assertEqual(metrics["baseline_target_cer"], 0.0)
        self.assertEqual(metrics["gated_target_cer"], 1.0)
        self.assertEqual(metrics["negative_acceptance_rate"], 1.0)
        self.assertEqual(metrics["accepted_non_target_hypothesis_characters"], 4)

    def test_recognizer_accepts_fp32_joiner_and_prefers_int8(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("encoder.int8.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt"):
                (root / name).write_bytes(b"x")
            with mock.patch.object(
                core.sherpa_onnx.OnlineRecognizer,
                "from_transducer",
                return_value="recognizer",
            ) as create:
                self.assertEqual(core.build_recognizer(root), "recognizer")
                self.assertEqual(create.call_args.kwargs["joiner"], str(root / "joiner.onnx"))

                (root / "joiner.int8.onnx").write_bytes(b"x")
                core.build_recognizer(root)
                self.assertEqual(
                    create.call_args.kwargs["joiner"], str(root / "joiner.int8.onnx")
                )

    def test_mix_at_snr_preserves_shape_and_requested_ratio(self) -> None:
        speech = np.full(16000, 0.1, dtype=np.float32)
        noise = np.linspace(-1.0, 1.0, 16000, dtype=np.float32)

        mixed = pilot.mix_at_snr(speech, noise, 10.0)
        added = mixed - speech
        measured = 20.0 * np.log10(
            np.sqrt(np.mean(np.square(speech))) / np.sqrt(np.mean(np.square(added)))
        )

        self.assertEqual(mixed.shape, speech.shape)
        self.assertAlmostEqual(float(measured), 10.0, places=3)

    def test_extractor_waveform_scale_is_explicit_and_validated(self) -> None:
        samples = np.array([-1.0, 0.5], dtype=np.float32)

        scaled = pilot.scale_waveform_for_extractor(samples, 32768.0)

        np.testing.assert_array_equal(scaled, np.array([-32768.0, 16384.0]))
        with self.assertRaises(ValueError):
            pilot.scale_waveform_for_extractor(samples, float("nan"))

    def test_window_score_aggregation_is_explicit(self) -> None:
        scores = [0.1, 0.6, 0.2]

        self.assertAlmostEqual(core.aggregate_window_scores(scores, "max"), 0.6)
        self.assertAlmostEqual(core.aggregate_window_scores(scores, "mean"), 0.3)
        self.assertAlmostEqual(core.aggregate_window_scores(scores, "median"), 0.2)
        with self.assertRaises(ValueError):
            core.aggregate_window_scores(scores, "unknown")

    def test_enrollment_noise_augmentation_keeps_clean_and_uses_noise(self) -> None:
        clean = np.full(8, 0.1, dtype=np.float32)
        noise = np.linspace(-1.0, 1.0, 8, dtype=np.float32)

        augmented = pilot.augment_enrollment_audio(
            [(clean, 16000)],
            [(pilot.NoiseSample("n1", Path("noise.wav")), noise)],
            [5.0, 0.0],
        )

        self.assertEqual(len(augmented), 3)
        np.testing.assert_array_equal(augmented[0][0], clean)
        self.assertFalse(np.array_equal(augmented[1][0], clean))
        self.assertFalse(np.array_equal(augmented[1][0], augmented[2][0]))
        with self.assertRaises(ValueError):
            pilot.augment_enrollment_audio([(clean, 16000)], [], [5.0])

    def test_load_audio_resamples_without_optional_librosa(self) -> None:
        import soundfile as sf

        with tempfile.TemporaryDirectory() as temporary:
            audio = Path(temporary) / "48k.wav"
            sf.write(audio, np.sin(np.linspace(0.0, 20.0, 48000)), 48000)

            samples, original_sample_rate = core.load_audio_mono16k(audio)

        self.assertEqual(original_sample_rate, 48000)
        self.assertEqual(len(samples), 16000)
        self.assertEqual(samples.dtype, np.float32)

    def test_denoise_audio_validates_runtime_output(self) -> None:
        class Result:
            samples = np.array([0.1, -0.1], dtype=np.float32)
            sample_rate = 16000

        denoiser = mock.Mock()
        denoiser.run.return_value = Result()

        samples, sample_rate = core.denoise_audio(
            denoiser, np.array([0.2, -0.2], dtype=np.float32), 16000
        )

        np.testing.assert_array_equal(samples, Result.samples)
        self.assertEqual(sample_rate, 16000)
        denoiser.run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
