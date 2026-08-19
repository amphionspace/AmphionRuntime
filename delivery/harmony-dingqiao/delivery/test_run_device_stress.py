from __future__ import annotations

import importlib.util
from array import array
import hashlib
import json
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
    def test_customer_tail_manifest_binds_expected_suffix_to_source_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "tail.json"
            source_hash = "a" * 64
            manifest.write_text(json.dumps({"files": [{
                "sha256": source_hash,
                "required_suffix": "12 34567。",
            }]}), encoding="utf-8")
            mapping = [{"id": "000000", "source_sha256": source_hash}]
            complete = [{"id": "000000", "resultHex": "正文，123 4567。".encode("utf-16-be").hex()}]
            truncated = [{"id": "000000", "resultHex": "正文，123 45。".encode("utf-16-be").hex()}]

            verdict = MODULE.expected_tail_verdict(complete, mapping, manifest)
            self.assertEqual("PASS", verdict["status"])
            self.assertNotIn("required_suffix", verdict["cases"][0])
            self.assertNotIn("normalized_result_suffix", verdict["cases"][0])
            self.assertEqual(hashlib.sha256(manifest.read_bytes()).hexdigest(),
                             verdict["manifest_sha256"])
            self.assertEqual("FAIL", MODULE.expected_tail_verdict(
                truncated, mapping, manifest)["status"])
            self.assertNotIn('"expected_tail_manifest":',
                             SCRIPT.read_text(encoding="utf-8"))

            manifest.write_text(json.dumps({"files": [
                {"sha256": source_hash, "required_suffix": "1234567"},
                {"sha256": source_hash, "required_suffix": "7654321"},
            ]}), encoding="utf-8")
            duplicate = MODULE.expected_tail_verdict(complete, mapping, manifest)
            self.assertEqual("FAIL", duplicate["status"])
            self.assertIn("duplicate sha256", duplicate["reason"])

    def test_customer_tail_manifest_requires_meeting_minutes_mode(self) -> None:
        with mock.patch.object(
            sys, "argv", [str(SCRIPT), "--mode", "burst", "--expected-tail-manifest", "tail.json"]
        ), self.assertRaises(SystemExit):
            MODULE.parse_args()

    def test_continuous_max_duration_requires_and_accepts_tail_manifest(self) -> None:
        with mock.patch.object(
            sys, "argv", [str(SCRIPT), "--mode", "continuous-max-duration"]
        ), self.assertRaises(SystemExit):
            MODULE.parse_args()

        with mock.patch.object(
            sys,
            "argv",
            [str(SCRIPT), "--mode", "continuous-max-duration",
             "--expected-tail-manifest", "tail.json"],
        ):
            args = MODULE.parse_args()
        self.assertEqual("continuous-max-duration", args.mode)
        self.assertIn("continuous-max-duration", MODULE.FINISH_MODES)

        carrier = CARRIER.read_text(encoding="utf-8")
        self.assertIn("params.extraParams['enableContinuousRecognition'] = true", carrier)
        self.assertIn("fed > requiredFrames", carrier)

    def test_continuous_long_and_voiceprint_speaker_vad_gates(self) -> None:
        modes = ("continuous-long-session", "continuous-voiceprint-speaker-vad")
        for mode in modes:
            with self.subTest(mode=mode), mock.patch.object(
                sys, "argv", [str(SCRIPT), "--mode", mode]
            ), self.assertRaises(SystemExit):
                MODULE.parse_args()

            with self.subTest(mode=mode), mock.patch.object(
                sys,
                "argv",
                [str(SCRIPT), "--mode", mode,
                 "--expected-tail-manifest", "tail.json"],
            ):
                args = MODULE.parse_args()
            self.assertEqual(mode, args.mode)
            self.assertIn(mode, MODULE.FINISH_MODES)

        with mock.patch.object(
            sys,
            "argv",
            [str(SCRIPT), "--mode", "continuous-long-session", "--cycles", "1",
             "--expected-tail-manifest", "tail.json"],
        ), self.assertRaises(SystemExit):
            MODULE.parse_args()
        with mock.patch.object(
            sys,
            "argv",
            [str(SCRIPT), "--mode", "continuous-long-session", "--cycles", "2",
             "--pace-ms", "0", "--expected-tail-manifest", "tail.json"],
        ), self.assertRaises(SystemExit):
            MODULE.parse_args()

        carrier = CARRIER.read_text(encoding="utf-8")
        cycle = carrier.split("async function runContinuousMaxDurationCycle", 1)[1].split(
            "async function runNumericEdgeCycle", 1
        )[0]
        self.assertIn("CONTINUOUS_LONG_MIN_FRAMES", cycle)
        self.assertIn("params.extraParams['enableVoiceprintVerification'] = true", cycle)
        self.assertIn("params.extraParams['enableSpeakerVad'] = true", cycle)
        self.assertIn("events.nonEmptySpeakerScores === nonEmptyFinals", cycle)
        self.assertIn("lastBeforeFinish === 0", cycle)
        runner = SCRIPT.read_text(encoding="utf-8")
        self.assertIn(
            'args.mode == "continuous-long-session" and memory.get("status") != "PASS"',
            runner,
        )

    def test_customer_meeting_minutes_requires_tail_manifest(self) -> None:
        with mock.patch.object(
            sys, "argv", [str(SCRIPT), "--mode", "customer-meeting-minutes"]
        ), self.assertRaises(SystemExit):
            MODULE.parse_args()

    def test_customer_tail_manifest_rejects_non_utf8_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "tail.json"
            manifest.write_bytes(b"\xff\xfe")

            verdict = MODULE.expected_tail_verdict([], [], manifest)

            self.assertEqual("FAIL", verdict["status"])
            self.assertIn("cannot read tail manifest", verdict["reason"])

    def test_voiceprint_representative_selection_excludes_too_short_enrollment(self) -> None:
        sources = [
            MODULE.AudioSource(Path("short.wav"), 16000, 1, 2, 44800, 2.8),
            MODULE.AudioSource(Path("long.wav"), 16000, 1, 2, 782080, 48.88),
            MODULE.AudioSource(Path("valid.wav"), 16000, 1, 2, 51680, 3.23),
        ]

        selected = MODULE.representative_voiceprint_sources(sources, 3)

        self.assertEqual(2, len(selected))
        self.assertTrue(all(source.duration_seconds >= 3.0 for source in selected))

    def test_voiceprint_fallback_uses_the_versioned_regression_fixtures(self) -> None:
        external = Path("/external/release-corpus")

        selected = MODULE.corpus_root_for_mode(external, "voiceprint-fallback")

        self.assertEqual(
            MODULE.REPO_ROOT / "asr/test-fixtures/voiceprint-fallback",
            selected,
        )
        self.assertEqual(external, MODULE.corpus_root_for_mode(external, "burst"))

    def test_speaker_turn_manifest_enforces_required_forbidden_text_and_final_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(
                '{"files":[{"role":"case","case_id":"S1","path":"case.wav",'
                '"required_texts":["主讲尾字"],"forbidden_texts":["其他开头"],'
                '"expected_nonempty_public_finals":1}]}',
                encoding="utf-8",
            )
            mapping = [{"id": "000000", "source": "case.wav"}]
            clean = [{"id": "000000", "resultHex": "主讲尾字".encode("utf-16-be").hex(),
                      "nonEmptyFinals": "1"}]
            leaked = [{"id": "000000", "resultHex": "主讲尾字其他开头".encode("utf-16-be").hex(),
                       "nonEmptyFinals": "1"}]
            truncated = [{"id": "000000", "resultHex": "主讲".encode("utf-16-be").hex(),
                          "nonEmptyFinals": "1"}]

            self.assertEqual("PASS", MODULE.target_speaker_content_verdict(
                clean, mapping, manifest)["status"])
            self.assertEqual("FAIL", MODULE.target_speaker_content_verdict(
                leaked, mapping, manifest)["status"])
            self.assertEqual("FAIL", MODULE.target_speaker_content_verdict(
                truncated, mapping, manifest)["status"])

    def test_speaker_turn_manifest_accepts_global_forbidden_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(
                '{"business_assertion":{"forbidden_text":"其他开头"},"files":['
                '{"role":"case","case_id":"S1","path":"case.wav",'
                '"required_texts":["主讲尾字"],"expected_nonempty_public_finals":1}]}',
                encoding="utf-8",
            )
            mapping = [{"id": "000000", "source": "case.wav"}]
            clean = [{"id": "000000", "resultHex": "主讲尾字".encode("utf-16-be").hex(),
                      "nonEmptyFinals": "1"}]
            leaked = [{"id": "000000", "resultHex": "主讲尾字其他开头".encode("utf-16-be").hex(),
                       "nonEmptyFinals": "1"}]

            self.assertEqual("PASS", MODULE.target_speaker_content_verdict(
                clean, mapping, manifest)["status"])
            self.assertEqual("FAIL", MODULE.target_speaker_content_verdict(
                leaked, mapping, manifest)["status"])

    def test_speaker_turn_mode_accepts_threshold_and_content_override(self) -> None:
        with mock.patch.object(
            sys,
            "argv",
            [
                str(SCRIPT),
                "--mode", "speaker-vad-turn",
                "--speaker-vad-threshold", "0.42",
                "--skip-target-content-check",
            ],
        ):
            args = MODULE.parse_args()
        self.assertEqual("speaker-vad-turn", args.mode)
        self.assertEqual(0.42, args.speaker_vad_threshold)
        self.assertTrue(args.skip_target_content_check)

    def test_speaker_turn_realtime_gate_uses_public_endpoint_to_final_latency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hilog = Path(directory) / "hilog.txt"
            hilog.write_text(
                "kind=UTTERANCE endpointToFinalLatencyMs=210\n"
                "kind=UTTERANCE endpointToFinalLatencyMs=990\n",
                encoding="utf-8",
            )
            passed = MODULE.speaker_turn_final_latency_verdict(hilog, required=True)
            self.assertEqual("PASS", passed["status"])
            self.assertEqual(990, passed["p95_endpoint_to_final_ms"])

            hilog.write_text(
                "kind=UTTERANCE endpointToFinalLatencyMs=990\n" * 20
                + "kind=UTTERANCE endpointToFinalLatencyMs=1001\n",
                encoding="utf-8",
            )
            failed = MODULE.speaker_turn_final_latency_verdict(hilog, required=True)
            self.assertEqual(990, failed["p95_endpoint_to_final_ms"])
            self.assertEqual("FAIL", failed["status"])

    def test_speaker_turn_finish_recovery_uses_finish_to_final_latency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hilog = Path(directory) / "hilog.txt"
            hilog.write_text("", encoding="utf-8")
            cycles = [
                {"id": "000003", "speechEndsBeforeFinish": "0", "finishToFirstNonEmptyResultMs": "640"},
                {"id": "000003", "speechEndsBeforeFinish": "0", "finishToFirstNonEmptyResultMs": "910"},
            ]

            passed = MODULE.speaker_turn_final_latency_verdict(
                hilog, required=True, cycles=cycles,
                finish_recovery_entry_ids={"000003"}
            )
            self.assertEqual("PASS", passed["status"])
            self.assertEqual(910, passed["p95_finish_to_final_ms"])
            self.assertEqual(2, passed["finish_recovery_count"])
            self.assertEqual(1200, passed["maximum_finish_latency_ms"])

            cycles[1]["finishToFirstNonEmptyResultMs"] = "1190"
            passed = MODULE.speaker_turn_final_latency_verdict(
                hilog, required=True, cycles=cycles,
                finish_recovery_entry_ids={"000003"}
            )
            self.assertEqual("PASS", passed["status"])

            cycles = [
                {"id": "000003", "speechEndsBeforeFinish": "0", "finishToFirstNonEmptyResultMs": "1190"}
                for _ in range(20)
            ]
            cycles.append(
                {"id": "000003", "speechEndsBeforeFinish": "0", "finishToFirstNonEmptyResultMs": "1201"}
            )
            failed = MODULE.speaker_turn_final_latency_verdict(
                hilog, required=True, cycles=cycles,
                finish_recovery_entry_ids={"000003"}
            )
            self.assertEqual(1190, failed["p95_finish_to_final_ms"])
            self.assertEqual("FAIL", failed["status"])

    def test_speaker_turn_manifest_enables_finish_recovery_per_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(
                '{"files":['
                '{"role":"case","path":"cases/short.wav","allow_finish_recovery":true},'
                '{"role":"case","path":"cases/ordinary.wav"}'
                ']}',
                encoding="utf-8",
            )
            self.assertEqual(
                {"cases/short.wav"},
                MODULE.target_speaker_manifest_finish_recovery_sources(manifest),
            )

    def test_installed_package_mode_is_explicit_and_exclusive(self) -> None:
        with mock.patch.object(sys, "argv", [str(SCRIPT), "--installed-package"]):
            args = MODULE.parse_args()
        self.assertTrue(args.installed_package)
        self.assertFalse(args.skip_build_install)

        with mock.patch.object(
            sys,
            "argv",
            [str(SCRIPT), "--installed-package", "--skip-build-install"],
        ), self.assertRaises(SystemExit):
            MODULE.parse_args()

    def test_installed_bundle_identity_uses_device_metadata(self) -> None:
        bundle = {
            "applicationInfo": {
                "bundleName": MODULE.BUNDLE,
                "versionName": "0.2.8",
                "versionCode": 208,
                "fingerprint": "abc",
            }
        }
        parsed = MODULE.parse_installed_bundle_info(
            f"{MODULE.BUNDLE}:\n" + __import__("json").dumps(bundle)
        )
        self.assertEqual(bundle, parsed)

    def test_cpu_statistics_reports_single_core_and_device_capacity(self) -> None:
        first = MODULE.MemorySample(0.0, 7, 1, 1, 1, 0, 1, 100, 1000, 4)
        second = MODULE.MemorySample(1.0, 7, 1, 1, 1, 0, 1, 120, 1200, 4)
        third = MODULE.MemorySample(2.0, 7, 1, 1, 1, 0, 1, 140, 1400, 4)

        result = MODULE.cpu_statistics([first, second, third])

        self.assertEqual("MEASURED", result["status"])
        self.assertEqual(40.0, result["mean_single_core_equivalent_percent"])
        self.assertEqual(10.0, result["mean_device_capacity_percent"])

    def test_proc_cpu_parsers_handle_process_name_and_logical_cpus(self) -> None:
        fields = ["S"] + ["0"] * 10 + ["12", "8"] + ["0"] * 8
        self.assertEqual(
            20,
            MODULE.parse_process_cpu_ticks("42 (demo process) " + " ".join(fields)),
        )
        self.assertEqual(
            (210, 2),
            MODULE.parse_system_cpu_ticks(
                "cpu 100 20 30 40 10 10 0 0 50 25\ncpu0 1\ncpu1 1\n"
            ),
        )

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
        self.assertIn(
            "endpointNonEmptySpeakerScores === endpointNonEmptyFinals", cycle
        )
        self.assertIn("lastFinalsBeforeFinish === 0", cycle)
        self.assertIn("params.extraParams['enableSpeakerVad'] = false", cycle)
        self.assertIn("params.extraParams['maxAudioDuration'] = 28800000", cycle)
        self.assertNotIn("MAX_DURATION_TEST_MS", cycle)
        runner = SCRIPT.read_text(encoding="utf-8")
        self.assertIn(
            'required_names = ("000_enroll.wav", "001_recognize.wav")',
            runner,
        )

    def test_voiceprint_multi_utterance_requires_every_nonempty_final_to_be_scored(
        self,
    ) -> None:
        source = CARRIER.read_text(encoding="utf-8")
        cycle = source.split("async function runVoiceprintCycle", 1)[1].split(
            "async function runVoiceprintVadBeginCycle", 1
        )[0]

        self.assertIn(
            "events.nonEmptySpeakerScores === nonEmptyFinals", cycle
        )
        self.assertIn(
            "scenario !== 'multi-utterance' || nonEmptyFinals >= 2", cycle
        )

    def test_zero_minimum_disables_voiceprint_initial_confirmation_grace(self) -> None:
        source = CARRIER.read_text(encoding="utf-8")
        idle_cycle = source.split(
            "async function runVoiceprintVadBeginIdleCycle", 1
        )[1].split("async function runSpeakerVadOnStartCycle", 1)[0]

        self.assertIn("result.confirmationGraceMs = 0", source)
        self.assertNotIn("result.confirmationGraceMs = 1500", source)
        self.assertIn("fed >= 45 && fed <= 70", idle_cycle)
        self.assertNotIn("fed >= 110 && fed <= 150", idle_cycle)

    def test_voiceprint_enrollment_reads_are_bounded_for_every_source(self) -> None:
        source = CARRIER.read_text(encoding="utf-8")
        prepare = source.split("function prepareStressVoiceprint", 1)[1].split(
            "async function feedPcmFile", 1
        )[0]
        self.assertIn(
            "const readBytes = Math.min(sourceBytes, 5 * 16000 * 2)", prepare
        )
        self.assertNotIn("entries.length > 1 ? sourceBytes", prepare)

    def test_max_duration_gate_covers_burst_and_paced_at_exact_frame_count(self) -> None:
        source = CARRIER.read_text(encoding="utf-8")
        cycle = source.split("async function runMaxDurationCycle", 1)[1].split(
            "async function runNumericEdgeCycle", 1
        )[0]

        self.assertIn("const MAX_DURATION_TEST_MS: number = 8000;", source)
        self.assertIn("const paced = index % 2 === 1;", cycle)
        self.assertIn("fedFrames < MAX_DURATION_TEST_FRAMES", cycle)
        self.assertIn("MAX_DURATION_TEST_FRAMES - fedFrames", cycle)
        self.assertNotIn("MAX_DURATION_TEST_FRAMES + 100", cycle)
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

        self.assertIn("params.extraParams['enablePartialResult'] = true", cycle)
        self.assertIn("events.nonEmptySpeakerScores > 0", cycle)
        self.assertIn("events.partials > 0", cycle)
        self.assertIn("speaker-vad-onstart-missing-partial", cycle)
        self.assertIn("speaker-vad-missing-nonempty-speaker-score", cycle)

    def test_same_source_speaker_modes_allow_the_only_entry_as_enrollment(self) -> None:
        source = CARRIER.read_text(encoding="utf-8")
        self.assertIn("options.enrollmentCount > entries.length", source)
        self.assertIn(
            "requiresSeparateCase && options.enrollmentCount === entries.length", source
        )

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

    def test_voiceprint_vad_begin_idle_paces_frames_for_async_completion(self) -> None:
        source = CARRIER.read_text(encoding="utf-8")
        cycle = source.split("async function runVoiceprintVadBeginIdleCycle", 1)[1].split(
            "async function runSpeakerVadOnStartCycle", 1
        )[0]

        self.assertIn("await sleep(IDLE_FRAME_PACE_MS);", cycle)
        self.assertIn(
            "const IDLE_FRAME_PACE_MS: number = FRAME_DURATION_MS + 10;", source
        )
        self.assertNotIn("if (fed % 10 === 0) await sleep(1);", cycle)

    def test_cancel_waits_for_async_native_stream_drain_without_relaxing_callbacks(self) -> None:
        source = CARRIER.read_text(encoding="utf-8")
        cycle = source.split("async function runRecognitionCycle", 1)[1].split(
            "async function runVadBeginSilenceCycle", 1
        )[0]

        self.assertIn(
            "const drained = await waitFor((): boolean => "
            "AmphionRuntime.activeOnlineStreamCount() === 0, CANCEL_DRAIN_TIMEOUT_MS);",
            " ".join(cycle.split()),
        )
        self.assertIn("drained && !engine.isBusy()", cycle)
        self.assertIn("events.finals === finalsBefore", cycle)
        self.assertIn("events.completes === completesBefore", cycle)
        self.assertIn("const CANCEL_DRAIN_TIMEOUT_MS: number = 2000;", source)
        self.assertIn("const CANCEL_CALLBACK_STABILITY_MS: number = 100;", source)
        drain_index = cycle.index("const drained = await waitFor")
        stability_index = cycle.index("await sleep(CANCEL_CALLBACK_STABILITY_MS)")
        contract_index = cycle.index("const ok = drained")
        self.assertLess(drain_index, stability_index)
        self.assertLess(stability_index, contract_index)

    def test_public_api_reentrant_modes_are_lifecycle_only(self) -> None:
        for mode in ("speaker-vad-onstart", "callback-api-reentrant"):
            with self.subTest(mode=mode), mock.patch.object(
                sys, "argv", [str(SCRIPT), "--mode", mode]
            ):
                args = MODULE.parse_args()

            self.assertEqual(mode, args.mode)
            self.assertNotIn(mode, MODULE.FINISH_MODES)

    def test_callback_api_reentrant_waits_for_async_audio_before_cancel(self) -> None:
        source = CARRIER.read_text(encoding="utf-8")
        cycle = source.split("async function runCallbackApiReentrantCycle", 1)[1].split(
            "async function runMaxDurationCycle", 1
        )[0]
        normalized = " ".join(cycle.split())

        self.assertIn(
            "waitFor((): boolean => listener.reentryAttempted, COMPLETE_TIMEOUT_MS)",
            normalized,
        )

    def test_callback_api_reentrant_requires_text_on_last_for_speech_end_finish(self) -> None:
        source = CARRIER.read_text(encoding="utf-8")
        cycle = source.split("async function runCallbackApiReentrantCycle", 1)[1].split(
            "async function runFinishShutdownCycle", 1
        )[0]
        normalized = " ".join(cycle.split())

        self.assertIn("events.lastFinals === 1 && events.finals >= 1", normalized)
        self.assertIn("if (trigger === 'speech-end')", cycle)
        self.assertIn("finalContract = finalContract && terminalText.length > 0", cycle)
        self.assertNotIn(
            "waitFor((): boolean => listener.reentryAttempted, 1000)", normalized
        )
        self.assertIn("listener.terminalOrderOk(sessionId)", cycle)

    def test_finish_shutdown_mode_preserves_accepted_finish_callbacks(self) -> None:
        with mock.patch.object(sys, "argv", [str(SCRIPT), "--mode", "finish-shutdown"]):
            args = MODULE.parse_args()

        self.assertEqual("finish-shutdown", args.mode)
        self.assertIn("finish-shutdown", MODULE.FINISH_MODES)
        source = CARRIER.read_text(encoding="utf-8")
        cycle = source.split("async function runFinishShutdownCycle", 1)[1].split(
            "async function runFinishShutdownRelicenseCycle", 1
        )[0]
        finish_index = cycle.index("engine.finish(sessionId)")
        busy_index = cycle.index("const busyAfterFinish = engine.isBusy()")
        shutdown_index = cycle.index("engine.shutdown()")
        complete_index = cycle.index("events.completes === 1")
        self.assertLess(finish_index, busy_index)
        self.assertLess(busy_index, shutdown_index)
        self.assertLess(shutdown_index, complete_index)
        self.assertIn("events.lastFinals === 1", cycle)
        self.assertIn("events.completes === 1", cycle)
        self.assertIn("terminalCallbackOrderOk(events, sessionId)", cycle)

    def test_terminal_callback_order_rejects_complete_before_last_and_any_late_callback(self) -> None:
        self.assertTrue(
            MODULE.terminal_callback_order_ok("s:start>s:final-last>s:complete")
        )
        self.assertFalse(
            MODULE.terminal_callback_order_ok("s:start>s:complete>s:final-last")
        )
        self.assertFalse(
            MODULE.terminal_callback_order_ok("s:start>s:final-last>s:complete>s:partial")
        )
        self.assertFalse(
            MODULE.terminal_callback_order_ok("s:start>s:final-last>s:complete>s:event-3")
        )
        self.assertFalse(
            MODULE.terminal_callback_order_ok("s:start>s:final-last>s:complete>s:error")
        )

    def test_finish_shutdown_relicense_mode_is_available_for_customer_race_reproduction(self) -> None:
        with mock.patch.object(
            sys, "argv", [str(SCRIPT), "--mode", "finish-shutdown-relicense"]
        ):
            args = MODULE.parse_args()
        self.assertEqual("finish-shutdown-relicense", args.mode)
        self.assertIn("finish-shutdown-relicense", MODULE.FINISH_MODES)
        source = CARRIER.read_text(encoding="utf-8")
        cycle = source.split("async function runFinishShutdownRelicenseCycle", 1)[1].split(
            "async function runMaxDurationCycle", 1
        )[0]
        finish_index = cycle.index("engine.finish(sessionId)")
        busy_index = cycle.index("const busyAfterFinish = engine.isBusy()")
        shutdown_index = cycle.index("engine.shutdown()")
        license_index = cycle.index("await activateLicense(licensePath)")
        prepare_index = cycle.index("await prepareRuntime()")
        complete_index = cycle.index("events.completes === 1")
        self.assertLess(finish_index, busy_index)
        self.assertLess(busy_index, shutdown_index)
        self.assertLess(shutdown_index, license_index)
        self.assertLess(license_index, prepare_index)
        self.assertLess(prepare_index, complete_index)
        self.assertIn("events.lastFinals === 1", cycle)
        self.assertIn("events.completes === 1", cycle)
        self.assertIn("terminalCallbackOrderOk(events, sessionId)", cycle)
        self.assertIn("recoveryEvents.starts === 1", cycle)
        self.assertIn("recoveryEvents.lastFinals === 1", cycle)
        self.assertIn("recoveryEvents.completes === 1", cycle)
        self.assertIn("recoveryEvents.unexpectedSessionCallbacks === 0", cycle)
        self.assertIn("terminalCallbackOrderOk(recoveryEvents, recoverySessionId)", cycle)

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

    def test_payload_records_source_and_converted_pcm_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "source.wav"
            with wave.open(str(path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16_000)
                wav.writeframes(array("h", [1, -1] * 320).tobytes())
            source = MODULE.AudioSource(path, 16_000, 1, 2, 640, 0.04)
            payload = root / "payload"

            mapping = MODULE.prepare_payload(
                [source], payload, "/remote/run", root
            )

            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                mapping[0]["source_sha256"],
            )
            pcm = payload / "audio" / "000000.pcm"
            self.assertEqual(
                hashlib.sha256(pcm.read_bytes()).hexdigest(),
                mapping[0]["pcm_sha256"],
            )


if __name__ == "__main__":
    unittest.main()
