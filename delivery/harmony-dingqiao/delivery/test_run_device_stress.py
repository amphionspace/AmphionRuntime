from __future__ import annotations

import importlib.util
from array import array
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import wave


SCRIPT = Path(__file__).with_name("run_device_stress.py")
CARRIER = (
    SCRIPT.parents[1]
    / "samples/dingqiao-demo/entry/src/main/ets/util/DeviceStressTest.ets"
)
SPEC = importlib.util.spec_from_file_location("run_device_stress", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RunCommandTest(unittest.TestCase):
    def test_voiceprint_fallback_is_a_dedicated_endpoint_score_gate(self) -> None:
        source = CARRIER.read_text(encoding="utf-8")
        cycle = source.split("async function runVoiceprintFallbackCycle", 1)[1].split(
            "async function runVoiceprintVadBeginIdleCycle", 1
        )[0]

        with mock.patch.object(
            sys, "argv", [str(SCRIPT), "--mode", "voiceprint-fallback"]
        ):
            args = MODULE.parse_args()

        self.assertEqual("voiceprint-fallback", args.mode)
        self.assertIn("events.firstNonEmptyFinalHasScore === true", cycle)
        self.assertIn("lastFinalsBeforeFinish === 0", cycle)
        self.assertIn("params.extraParams['enableSpeakerVad'] = false", cycle)
        self.assertIn("params.extraParams['maxAudioDuration'] = 28800000", cycle)
        self.assertNotIn("MAX_DURATION_TEST_MS", cycle)
        runner = SCRIPT.read_text(encoding="utf-8")
        self.assertIn(
            'required_names = ("000_enroll.wav", "001_recognize.wav")',
            runner,
        )

    def test_max_duration_gate_covers_burst_and_paced_at_exact_frame_count(self) -> None:
        source = CARRIER.read_text(encoding="utf-8")
        cycle = source.split("async function runMaxDurationCycle", 1)[1].split(
            "async function runNumericEdgeCycle", 1
        )[0]

        self.assertIn("const MAX_DURATION_TEST_MS: number = 8000;", source)
        self.assertIn("const paced = index % 2 === 1;", cycle)
        self.assertIn("fedFrames === MAX_DURATION_TEST_FRAMES", cycle)
        self.assertIn("result.requestedMaxAudioDurationMs = MAX_DURATION_TEST_MS", cycle)
        self.assertIn("result.effectiveMaxAudioDurationMs = MAX_DURATION_TEST_MS", cycle)

    def test_endpoint_reentrant_snapshots_every_callback_kind(self) -> None:
        source = CARRIER.read_text(encoding="utf-8")
        sequence_listener = source.split("class SequenceListener", 1)[1].split(
            "class CallbackApiReentrantListener", 1
        )[0]
        endpoint_listener = source.split("class EndpointReentrantListener", 1)[1].split(
            "class ReentrantCompleteListener", 1
        )[0]
        endpoint_cycle = source.split("async function runEndpointReentrantCycle", 1)[1].split(
            "async function runUserSequenceCycle", 1
        )[0]

        self.assertIn("sessionTrace(sessionId: string): string", sequence_listener)
        for kind in ("start", "partial", "event", "final", "complete", "error"):
            self.assertIn(f"'{kind}'", sequence_listener)
        for kind in ("event", "final", "error"):
            self.assertIn(f"record.kind === '{kind}'", sequence_listener)
        self.assertIn(
            "this.oldTraceAtSwitch = this.sessionTrace(this.oldSessionId)",
            endpoint_listener,
        )
        self.assertIn("callback.kind !== 'start'", endpoint_listener)
        self.assertIn("oldStableBeforeNewAudio", endpoint_cycle)
        self.assertIn("oldStableAfterNewSession", endpoint_cycle)
        self.assertIn("listener.sessionTrace(newSessionId) === 'start'", endpoint_cycle)

    def test_speaker_vad_onstart_requires_a_scored_nonempty_final(self) -> None:
        source = CARRIER.read_text(encoding="utf-8")
        cycle = source.split("async function runSpeakerVadOnStartCycle", 1)[1].split(
            "async function runCallbackApiReentrantCycle", 1
        )[0]

        self.assertIn("events.nonEmptySpeakerScores > 0", cycle)
        self.assertIn("speaker-vad-missing-nonempty-speaker-score", cycle)

    def test_voiceprint_vad_begin_scores_speech_even_when_asr_text_is_empty(self) -> None:
        source = CARRIER.read_text(encoding="utf-8")
        cycle = source.split("async function runVoiceprintVadBeginCycle", 1)[1].split(
            "async function runVoiceprintVadBeginIdleCycle", 1
        )[0]
        normalized = " ".join(cycle.split())

        self.assertIn("events.speakerScores > 0", cycle)
        self.assertIn(
            "events.finalChars === 0 || events.firstNonEmptyFinalHasScore === true",
            normalized,
        )
        self.assertIn(
            "events.finalChars > 0 && events.firstNonEmptyFinalHasScore !== true",
            cycle,
        )
        self.assertNotIn(
            "events.speakerScores > 0 && events.firstNonEmptyFinalHasScore === true",
            normalized,
        )

    def test_public_api_reentrant_modes_are_lifecycle_only(self) -> None:
        for mode in ("speaker-vad-onstart", "callback-api-reentrant"):
            with self.subTest(mode=mode), mock.patch.object(
                sys, "argv", [str(SCRIPT), "--mode", mode]
            ):
                args = MODULE.parse_args()

            self.assertEqual(mode, args.mode)
            self.assertNotIn(mode, MODULE.FINISH_MODES)

    def test_endpoint_reentrant_is_lifecycle_only_not_text_quality(self) -> None:
        with mock.patch.object(sys, "argv", [str(SCRIPT), "--mode", "endpoint-reentrant"]):
            args = MODULE.parse_args()

        self.assertEqual("endpoint-reentrant", args.mode)
        self.assertNotIn("endpoint-reentrant", MODULE.FINISH_MODES)

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
