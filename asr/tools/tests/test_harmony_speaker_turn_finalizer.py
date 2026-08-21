import hashlib
import json
import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
FINALIZER = (
    REPO_ROOT
    / "asr/harmony/sdk/src/main/ets/com/amphion/asr/SpeakerTurnFinalizer.ts"
)
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"
TS_LOADER = REPO_ROOT / "asr/tools/tests/ts_extension_loader.mjs"
C1_DIARIZATION = (
    REPO_ROOT
    / "asr/tools/testdata/speaker_turn/c1_sequential_diarization.json"
)
SPEAKER_TURN_MODEL = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/resources/rawfile/amphion-dingqiao/"
    "pyannote-segmentation-3.0.onnx"
)
SPEAKER_TURN_MODEL_METADATA = (
    REPO_ROOT
    / "delivery/harmony-dingqiao/delivery/pyannote_segmentation_3_0.json"
)
SPEAKER_TURN_NATIVE = (
    REPO_ROOT / "asr/harmony/sdk/src/main/cpp/speaker_turn_segmenter.cpp"
)
DEVICE_STRESS = (
    REPO_ROOT
    / "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/util/DeviceStressTest.ets"
)
SPEECH_RECOGNIZE_SDK = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
)
ANDROID_DINGQIAO_ENGINE = (
    REPO_ROOT
    / "asr/android/sdk-dingqiao/src/main/java/com/amphion/dingqiao/DingqiaoRecognitionEngine.kt"
)
ANDROID_SESSION_IMPL = (
    REPO_ROOT / "asr/android/sdk/src/main/java/com/amphion/asr/internal/SessionImpl.kt"
)


class HarmonySpeakerTurnFinalizerTest(unittest.TestCase):
    def run_finalizer(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ SpeakerTurnFinalizer, SpeakerTurnSegment, shouldRejectSpeakerVadFinal }}
              from {FINALIZER.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            [
                "node",
                "--experimental-strip-types",
                "--experimental-loader",
                TS_LOADER.as_uri(),
                "--input-type=module",
                "-e",
                script,
            ],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_sequential_turn_uses_quiet_valley_and_replays_suffix(self) -> None:
        self.run_finalizer(
            """
            const samples = new Float32Array(3_600);
            for (let i = 0; i < 2_000; i++) samples[i] = i % 2 === 0 ? 0.2 : -0.2;
            for (let i = 2_200; i < samples.length; i++) samples[i] = i % 2 === 0 ? 0.15 : -0.15;

            const finalizer = new SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000);
            finalizer.accept(samples);
            assert.equal(finalizer.observeScore(2_000, 0.65, 0.35), 'target-confirmed');
            assert.equal(finalizer.observeScore(3_000, 0.20, 0.35), 'below');
            assert.equal(finalizer.observeScore(3_200, 0.10, 0.35), 'departure');

            const split = finalizer.resolve([0.3, 1.0, 2.2], 0.35,
              (_samples, start, end) => end <= 2_200 ? 0.60 : start >= 2_200 ? 0.10 : undefined);
            assert.ok(split);
            assert.equal(split.cutSample, 2_200);
            assert.equal(split.prefix.length, 2_200);
            assert.equal(split.suffix.length, 1_400);
            assert.equal(split.suffix[0], samples[2_200]);
            """
        )

    def test_split_preserves_aligned_raw_and_agc_domains(self) -> None:
        self.run_finalizer(
            """
            const raw = new Float32Array(3_600);
            for (let i = 0; i < 2_000; i++) raw[i] = i % 2 === 0 ? 0.2 : -0.2;
            for (let i = 2_200; i < raw.length; i++) raw[i] = i % 2 === 0 ? 0.15 : -0.15;
            const processed = Float32Array.from(raw, value => value * 2);
            const finalizer = new SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000);
            finalizer.accept(raw, processed);
            finalizer.observeScore(2_000, 0.65, 0.35);
            finalizer.observeScore(3_000, 0.20, 0.35);
            finalizer.observeScore(3_200, 0.10, 0.35);
            const split = finalizer.resolve([0.3, 1.0, 2.2], 0.35,
              (_samples, start, end) => end <= 2_200 ? 0.60 : start >= 2_200 ? 0.10 : undefined);
            assert.ok(split);
            assert.equal(split.processedPrefix.length, split.prefix.length);
            assert.equal(split.processedSuffix.length, split.suffix.length);
            assert.equal(split.processedPrefix[100], split.prefix[100] * 2);
            assert.equal(split.processedSuffix[100], split.suffix[100] * 2);
            """
        )

    def test_finish_rejects_replayed_suffix_without_a_confirmed_target(self) -> None:
        self.run_finalizer(
            """
            assert.equal(shouldRejectSpeakerVadFinal(true, true, false), true);
            assert.equal(shouldRejectSpeakerVadFinal(true, false, false), true);
            assert.equal(shouldRejectSpeakerVadFinal(true, false, true), false);
            assert.equal(shouldRejectSpeakerVadFinal(false, true, false), false);
            """
        )

    def test_clean_split_keeps_a_replayed_non_target_tail_rejected(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        commit = source.split("private commitCleanSpeakerTurn", 1)[1].split(
            "private resolveSpeakerTurnSplit", 1
        )[0]
        reset = source.split("private resetSpeakerVadState", 1)[1].split(
            "private speakerTurnFinalizer", 1
        )[0]
        sync = source.split("private syncSpeakerTurnState", 1)[1].split(
            "private commitCleanSpeakerTurn", 1
        )[0]
        replay_index = commit.index("this.replaySpeakerSuffix(split)")
        departure_index = commit.index("this.svAwaitingTargetAfterDeparture = true")
        self.assertLess(departure_index, replay_index)
        self.assertIn(
            "this.svRejectCurrentUtterance = this.svAwaitingTargetAfterDeparture",
            reset,
        )
        self.assertIn(
            "if (this.svTargetConfirmed) this.svAwaitingTargetAfterDeparture = false",
            sync,
        )

    def test_known_non_target_tail_still_attempts_a_real_final_score(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        dispatch = source.split("private dispatchFinal", 1)[1].split(
            "private deliverSpeakerFinal", 1
        )[0]
        scoring_gate = dispatch.split(
            "if (this.speakerVadEnabled &&", 1
        )[1].split("const finalSpeakerVadScore", 1)[0]
        self.assertNotIn("!this.svRejectCurrentUtterance", scoring_gate)

    def test_finish_time_split_publishes_prefix_before_unique_last_tail(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        commit = source.split("private commitCleanSpeakerTurn", 1)[1].split(
            "private resolveSpeakerTurnSplit", 1
        )[0]
        endpoint = commit.index("this.callback.onEndpoint?.()")
        prefix_dispatch = commit.index(
            "this.dispatchFinal(endpointTriggered || finishTriggered"
        )
        replay = commit.index("this.replaySpeakerSuffix(split)")
        tail_last = commit.index("this.drain(true, false, true)")
        self.assertIn("const prefixIsLast = isLast && !finishTriggered", commit)
        self.assertLess(endpoint, prefix_dispatch)
        self.assertLess(prefix_dispatch, replay)
        self.assertLess(replay, tail_last)
        self.assertIn("if (finishTriggered && !this.callbackGate.isClosed())", commit)
        self.assertIn("this.reentryQueue.consumeStopAtEndpoint()", commit)

    def test_finish_uses_final_score_for_short_target_without_stream_confirmation(self) -> None:
        self.run_finalizer(
            """
            // A short utterance can finish before the first streaming Speaker VAD window. Once
            // ASR has speech evidence, the final score must decide the gate instead of the missing
            // streaming confirmation by itself.
            assert.equal(shouldRejectSpeakerVadFinal(true, false, false, true), false);
            assert.equal(shouldRejectSpeakerVadFinal(true, false, false, false), true);
            assert.equal(shouldRejectSpeakerVadFinal(true, true, false, true), true);
            """
        )

    def test_runtime_scores_short_speech_before_the_speaker_vad_final_gate(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        dispatch = source.split("private dispatchFinal", 1)[1].split(
            "private deliverSpeakerFinal", 1
        )[0]
        self.assertIn("let finalSpeakerVadMatch", dispatch)
        self.assertLess(
            dispatch.index("let finalSpeakerVadMatch"),
            dispatch.index("shouldRejectSpeakerVadFinal"),
        )
        self.assertNotIn("lastSpeakerVadScore: number = -1", source)

    def test_rejected_final_routing_does_not_require_voiceprint_verification(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        delivery = source.split("private deliverSpeakerFinal", 1)[1].split(
            "private flushPendingSpeakerFinals", 1
        )[0]
        self.assertIn("if (pending.result.isTargetSpeaker === false)", delivery)
        self.assertNotIn(
            "this.targetSpeakerEnabled && pending.result.isTargetSpeaker === false",
            delivery,
        )

    def test_packaged_boundary_model_matches_pinned_upstream_artifact(self) -> None:
        metadata = json.loads(SPEAKER_TURN_MODEL_METADATA.read_text(encoding="utf-8"))
        digest = hashlib.sha256(SPEAKER_TURN_MODEL.read_bytes()).hexdigest()
        self.assertEqual(metadata["sha256"], digest)
        self.assertEqual(
            "733a93b6473d019a773298e08cefa686894b1854",
            metadata["source_revision"],
        )

    def test_boundary_model_loader_supports_rawfile_and_absolute_speaker_paths(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        loader = source.split("static getOrCreateSpeakerTurnSegmenterAsync", 1)[1].split(
            "static async getOrCreateSpeakerExtractorAsync", 1
        )[0]
        self.assertIn("fileIo.openSync(segmentationModelPath)", loader)
        self.assertIn("context.resourceManager.getRawFileContentSync", loader)
        self.assertNotIn("absolute speaker model has no bundled segmentation peer", loader)

    def test_boundary_model_is_optional_for_existing_speaker_vad_layouts(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        loader = source.split("private ensureSpeakerTurnSegmenterLoad", 1)[1].split(
            "isClosed(): boolean", 1
        )[0]
        resolver = source.split("private resolveSpeakerTurnSplit", 1)[1].split(
            "private replaySpeakerSuffix", 1
        )[0]
        self.assertIn("speakerTurnSegmenterUnavailable = true", loader)
        self.assertIn("using acoustic resolver", loader)
        self.assertNotIn("this.close()", loader)
        self.assertIn("resolveSpeakerTurnAcoustic(finalizer, config, [], 'unavailable')", resolver)

    def test_native_segmenter_uses_model_declared_io_names(self) -> None:
        source = SPEAKER_TURN_NATIVE.read_text(encoding="utf-8")
        self.assertIn("GetInputNameAllocated(0, allocator)", source)
        self.assertIn("GetOutputNameAllocated(0, allocator)", source)
        self.assertNotIn('const char* input_names[] = {"x"}', source)

    def test_harmony_falls_back_to_bounded_acoustic_resolver_on_diarization_conflict(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        resolver = source.split("private resolveSpeakerTurnSplit", 1)[1].split(
            "private replaySpeakerSuffix", 1
        )[0]
        self.assertIn("if (diarizedSplit !== undefined) return diarizedSplit", resolver)
        self.assertIn("finalizer.resolve(speculative.timestamps", resolver)
        self.assertIn("boundaryHints", resolver)
        self.assertIn("resolver=acoustic-fallback", resolver)

    def test_async_lane_advances_vad_and_queues_speaker_work_before_decode(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        async_lane = source.split("private async feedChunkAndDecodeAsync", 1)[1].split(
            "// Acoustic activity only grants", 1
        )[0]
        accept_index = async_lane.index(
            "this.speakerTurnFinalizer(speakerVad).accept(rawSamples, processedSamples)"
        )
        vad_index = async_lane.index("await this.advanceVadGateAsync(rawSamples, replay)")
        speaker_index = async_lane.index("this.enqueueSpeakerVadInference(rawSamples.length)")
        decode_index = async_lane.index("await this.feedRecognizerAsync(processedSamples, false)")
        self.assertLess(accept_index, vad_index)
        self.assertLess(vad_index, speaker_index)
        self.assertLess(speaker_index, decode_index)
        self.assertNotIn("await this.enqueueSpeakerVadInference", async_lane)

    def test_async_finish_commits_a_pending_clean_speaker_turn(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        async_stop = source.split("private async stopNowAsync", 1)[1].split(
            "updateHotwords", 1
        )[0]
        self.assertIn("if (await this.commitSpeakerTurnAtFinishAsync()) return", async_stop)
        commit = source.split("private commitSpeakerTurnAtFinish", 1)[1].split(
            "setTargetSpeaker", 1
        )[0]
        self.assertIn(
            "const finishRecovery = finalizer.hasPendingFinishDeparture()",
            commit,
        )
        self.assertIn(
            "const finishDiarization = finalizer.hasFinishDiarizationCandidate()",
            commit,
        )
        self.assertIn(
            "!finalizer.hasPendingDeparture() && !finishRecovery && !finishDiarization",
            commit,
        )
        commit_index = async_stop.index("this.commitSpeakerTurnAtFinishAsync()")
        speculative_flush_index = async_stop.index("this.appendFinalTailSilence()")
        self.assertLess(commit_index, speculative_flush_index)

    def test_sync_finish_uses_the_same_short_departure_recovery(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        sync_stop = source.split("private stopNow(): void", 1)[1].split(
            "private async stopNowAsync", 1
        )[0]
        self.assertIn("if (this.commitSpeakerTurnAtFinish()) return", sync_stop)
        commit_index = sync_stop.index("this.commitSpeakerTurnAtFinish()")
        speculative_flush_index = sync_stop.index("this.appendFinalTailSilence()")
        self.assertLess(commit_index, speculative_flush_index)

    def test_enabled_by_default_starts_boundary_model_loading(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        constructor = source.split("constructor(sessionId:", 1)[1].split(
            "acceptPcm16", 1
        )[0]
        self.assertIn(
            "if (this.speakerVadEnabled) this.ensureSpeakerTurnSegmenterLoad()",
            constructor,
        )

    def test_missing_target_config_disables_default_speaker_vad_without_throwing(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        loader = source.split("private ensureSpeakerTurnSegmenterLoad", 1)[1].split(
            "ensureSpeakerTurnSegmenterReady", 1
        )[0]
        missing_target = loader.split("if (target === undefined)", 1)[1].split(
            "if (isSpeakerTurnSegmentationModelLoaded()", 1
        )[0]
        self.assertIn("this.speakerVadEnabled = false", missing_target)
        self.assertIn("Logger.w", missing_target)
        self.assertNotIn("throw new Error", missing_target)

    def test_clean_redecode_failure_is_reported_as_decode_failure(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        commit = source.split("private commitCleanSpeakerTurn", 1)[1].split(
            "private resolveSpeakerTurnSplit", 1
        )[0]
        self.assertIn("AsrErrorCode.DECODE_FAILED", commit)
        self.assertNotIn("AsrErrorCode.NATIVE_CRASH", commit)

    def test_endpoint_latency_starts_before_clean_prefix_redecode(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        endpoint = source.split("private triggerSpeakerVadEndpoint", 1)[1].split(
            "private resetSpeakerVadState", 1
        )[0]
        timestamp_index = endpoint.index("this.endpointAtMs = Date.now()")
        commit_index = endpoint.index("this.commitCleanSpeakerTurn(stopAtEndpoint, true)")
        self.assertLess(timestamp_index, commit_index)
        self.assertIn(
            "endpointTriggered ? this.endpointAtMs : -1",
            source,
        )

    def test_clean_prefix_similarity_is_computed_before_the_endpoint_once(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        departure = source.split("if (state === 'departure'", 1)[1].split(
            "private speakerVadScoreScheduler", 1
        )[0]
        clean_split = departure.split("this.svPendingSplit = split", 1)[1]
        self.assertLess(
            clean_split.index("this.prepareCleanPrefixSpeakerScore(split)"),
            clean_split.index("this.triggerSpeakerVadEndpoint()"),
        )
        delivery = source.split("private deliverSpeakerFinal", 1)[1].split(
            "private flushPendingSpeakerFinals", 1
        )[0]
        self.assertIn(
            "pending.result.speakerScore === undefined", delivery
        )
        precompute = source.split("private prepareCleanPrefixSpeakerScore", 1)[1].split(
            "private syncSpeakerTurnState", 1
        )[0]
        self.assertNotIn("targetSpeakerEnabled", precompute)

    def test_low_score_predecodes_only_the_immutable_prefix_before_endpoint(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        commit = source.split("private commitCleanSpeakerTurn", 1)[1].split(
            "private resolveSpeakerTurnSplit", 1
        )[0]
        speaker_gate = source.split("private maybeTriggerSpeakerVadEndpoint", 1)[1].split(
            "private speakerVadScoreScheduler", 1
        )[0]
        prepare_index = speaker_gate.index("this.prepareSpeakerTurnPrefix(finalizer)")
        departure_index = speaker_gate.index("if (state === 'departure'")
        endpoint_index = speaker_gate.index("this.triggerSpeakerVadEndpoint()", departure_index)
        self.assertLess(prepare_index, endpoint_index)
        self.assertIn("preparedSamples < split.prefix.length", commit)
        self.assertIn("this.appendFinalTailSilence()", commit)
        self.assertNotIn("CLEAN_PREFIX_FINAL_TAIL_SILENCE_MS", source)

    def test_safe_predecode_watermark_is_before_the_score_transition_band(self) -> None:
        self.run_finalizer(
            """
            const finalizer = new SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000);
            finalizer.accept(new Float32Array(3_000));
            finalizer.observeScore(2_000, 0.65, 0.35);
            assert.equal(finalizer.safePrefixEndSample(), 1_000);
            finalizer.observeScore(2_400, 0.20, 0.35);
            assert.equal(finalizer.safePrefixEndSample(), 1_000);
            """
        )

    def test_speaker_turn_accuracy_requires_endpoint_or_bounded_finish_recovery(self) -> None:
        carrier = DEVICE_STRESS.read_text(encoding="utf-8")
        cycle = carrier.split("async function runSpeakerVadTurnCycle", 1)[1].split(
            "function enableTargetSpeakerEnhancement", 1
        )[0]
        self.assertIn("const speechEndsBeforeFinish = events.speechEnds", cycle)
        self.assertIn("options.speakerVadFinishRecoveryEntryIds", cycle)
        self.assertIn("speechEndsBeforeFinish > 0 || finishRecovery", cycle)
        self.assertIn("finishToFirstNonEmptyResultMs <= 1200", cycle)
        self.assertIn("events.partials > 0", cycle)
        self.assertIn("speaker-vad-turn-missing-endpoint", cycle)

    def test_diarization_rejects_more_than_one_target_to_other_turn(self) -> None:
        self.run_finalizer(
            f"""
            const fixture = JSON.parse(await import('node:fs/promises').then(fs =>
              fs.readFile({str(C1_DIARIZATION)!r}, 'utf8')));
            const samples = new Float32Array(fixture.total_samples);
            samples.fill(0.1);
            const finalizer = new SpeakerTurnFinalizer(
              fixture.sample_rate, 24_000, 8_000, 2, fixture.total_samples);
            finalizer.accept(samples);
            finalizer.observeScore(96_000, 0.459, 0.35);
            finalizer.observeScore(104_000, 0.072, 0.35);
            finalizer.observeScore(112_000, -0.036, 0.35);

            const split = finalizer.resolveDiarized(
              fixture.segments.map(segment => new SpeakerTurnSegment(
                segment.start_sample, segment.end_sample, segment.speaker)),
              0.35,
              (_samples, speaker) => fixture.cluster_scores[String(speaker)]);

            assert.equal(split, undefined);
            assert.equal(finalizer.lastResolutionReason(),
              'diarization-turn-order:0-1-0-1');
            """
        )

    def test_finish_resolves_a_short_sequential_suffix_before_confirmed_departure(self) -> None:
        self.run_finalizer(
            """
            const samples = new Float32Array(70_400);
            samples.fill(0.2, 0, 48_000);
            samples.fill(0.1, 48_000);
            const finalizer = new SpeakerTurnFinalizer(16_000, 24_000, 8_000, 2, 70_400);
            finalizer.accept(samples);
            assert.equal(finalizer.observeScore(48_000, 0.62, 0.35), 'target-confirmed');
            assert.equal(finalizer.observeScore(64_000, 0.08, 0.35), 'below');
            assert.equal(finalizer.hasPendingDeparture(), false);
            assert.equal(finalizer.hasPendingFinishDeparture(), true);

            const segments = [
              new SpeakerTurnSegment(0, 48_000, 0),
              new SpeakerTurnSegment(48_000, 70_400, 1),
            ];
            const ordinary = finalizer.resolveDiarized(
              segments, 0.35, (_samples, speaker) => speaker === 0 ? 0.62 : 0.08);
            assert.equal(ordinary, undefined);

            let finishScoreCalls = 0;
            const atFinish = finalizer.resolveDiarizedAtFinish(
              segments, 0.35, (_samples, speaker) => {
                finishScoreCalls += 1;
                return speaker === 0 ? 0.62 : 0.08;
              });
            assert.ok(atFinish);
            assert.equal(finishScoreCalls, 1);
            assert.equal(atFinish.cutSample, 48_000);
            assert.equal(atFinish.prefix.length, 48_000);
            assert.equal(atFinish.suffix.length, 22_400);
            """
        )

    def test_finish_uses_diarization_when_short_suffix_misses_streaming_low_window(self) -> None:
        self.run_finalizer(
            """
            // Preserve target-only and overlap fail-open behavior; only a simple non-overlapping
            // target -> other diarization with a strong score margin may recover this short tail.
            const finalizer = new SpeakerTurnFinalizer(16_000, 24_000, 8_000, 2, 67_200);
            finalizer.accept(new Float32Array(67_200));
            assert.equal(finalizer.observeScore(56_000, 0.42, 0.35), 'target-confirmed');
            assert.equal(finalizer.hasPendingFinishDeparture(), false);

            const split = finalizer.resolveDiarizedAtFinish([
              new SpeakerTurnSegment(0, 48_000, 0),
              new SpeakerTurnSegment(48_000, 67_200, 1),
            ], 0.35, (_samples, speaker) => speaker === 0 ? 0.42 : 0.08);

            assert.ok(split);
            assert.equal(split.cutSample, 48_000);
            assert.equal(split.prefix.length, 48_000);
            assert.equal(split.suffix.length, 19_200);
            """
        )
        source = RUNTIME.read_text(encoding="utf-8")
        resolver = source.split("private resolveSpeakerTurnSplit", 1)[1].split(
            "private resolveSpeakerTurnAcoustic", 1
        )[0]
        self.assertIn(
            "resolveDiarizedAtFinish(resolvedSegments, config.threshold, scoreCluster, false)",
            resolver,
        )

    def test_finish_keeps_ambiguous_short_suffix_fail_open(self) -> None:
        self.run_finalizer(
            """
            const finalizer = new SpeakerTurnFinalizer(16_000, 24_000, 8_000, 2, 70_400);
            finalizer.accept(new Float32Array(70_400));
            finalizer.observeScore(48_000, 0.40, 0.35);
            finalizer.observeScore(64_000, 0.30, 0.35);

            const split = finalizer.resolveDiarizedAtFinish([
              new SpeakerTurnSegment(0, 48_000, 0),
              new SpeakerTurnSegment(48_000, 70_400, 1),
            ], 0.35, (_samples, speaker) => speaker === 0 ? 0.40 : 0.30);

            assert.equal(split, undefined);
            assert.match(finalizer.lastResolutionReason(), /diarization-finish-score-margin/);
            """
        )

    def test_finish_keeps_a_contiguous_diarized_boundary_fail_open(self) -> None:
        self.run_finalizer(
            """
            const finalizer = new SpeakerTurnFinalizer(16_000, 24_000, 8_000, 2, 70_400);
            finalizer.accept(new Float32Array(70_400));
            finalizer.observeScore(48_000, 0.62, 0.35);
            finalizer.observeScore(64_000, 0.08, 0.35);

            const split = finalizer.resolveDiarizedAtFinish([
              new SpeakerTurnSegment(0, 48_000, 0),
              new SpeakerTurnSegment(48_000, 70_400, 1),
            ], 0.35, (_samples, speaker) => speaker === 0 ? 0.62 : 0.08, true);

            assert.equal(split, undefined);
            assert.equal(finalizer.lastResolutionReason(),
              'diarization-contiguous-boundary:48000');
            """
        )

    def test_diarized_boundary_must_agree_with_speaker_score_transition(self) -> None:
        self.run_finalizer(
            """
            const samples = new Float32Array(64_000);
            samples.fill(0.1);
            const finalizer = new SpeakerTurnFinalizer(16_000, 24_000, 8_000, 2, 64_000);
            finalizer.accept(samples);
            finalizer.observeScore(48_000, 0.363, 0.35);
            finalizer.observeScore(56_000, -0.038, 0.35);
            finalizer.observeScore(64_000, 0.031, 0.35);

            const split = finalizer.resolveDiarized([
              new SpeakerTurnSegment(6_000, 20_000, 0),
              new SpeakerTurnSegment(20_000, 52_000, 1),
              new SpeakerTurnSegment(52_000, 64_000, 0),
            ], 0.35, (_samples, speaker) => speaker === 0 ? 0.526 : 0.088);

            assert.equal(split, undefined);
            assert.equal(finalizer.lastResolutionReason(),
              'diarization-turn-order:0-1-0');
            """
        )

    def test_contiguous_diarized_boundary_requires_independent_refinement(self) -> None:
        self.run_finalizer(
            """
            const resolve = (rightStart) => {
              const finalizer = new SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 4_000);
              finalizer.accept(new Float32Array(4_000));
              finalizer.observeScore(2_500, 0.62, 0.35);
              finalizer.observeScore(3_000, 0.12, 0.35);
              finalizer.observeScore(3_200, 0.08, 0.35);
              return finalizer.resolveDiarized([
                new SpeakerTurnSegment(0, 2_000, 0),
                new SpeakerTurnSegment(rightStart, 4_000, 1),
              ], 0.35, (_samples, speaker) => speaker === 0 ? 0.62 : 0.08, true);
            };

            const contiguous = resolve(2_000);
            assert.equal(contiguous, undefined);

            const quietGap = resolve(2_100);
            assert.ok(quietGap);
            assert.equal(quietGap.cutSample, 2_100);

            const finalizer = new SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 4_000);
            finalizer.accept(new Float32Array(4_000));
            finalizer.observeScore(2_500, 0.62, 0.35);
            finalizer.observeScore(3_000, 0.12, 0.35);
            finalizer.observeScore(3_200, 0.08, 0.35);
            const refined = finalizer.resolve([2.4], 0.35,
              (_samples, start, end) => {
                if (start === 1_000 && end === 2_000) return 0.62;
                if (start === 2_000 && end === 3_000) return 0.30;
                if (start === 1_400 && end === 2_400) return 0.62;
                if (start === 2_400 && end === 3_400) return 0.08;
                return undefined;
              }, [2_000]);
            assert.ok(refined);
            assert.equal(refined.cutSample, 2_400);
            """
        )

    def test_diarized_boundary_rejects_an_ambiguous_score_margin(self) -> None:
        self.run_finalizer(
            """
            const finalizer = new SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 4_000);
            finalizer.accept(new Float32Array(4_000));
            finalizer.observeScore(2_500, 0.40, 0.35);
            finalizer.observeScore(3_000, 0.30, 0.35);
            finalizer.observeScore(3_200, 0.29, 0.35);

            const split = finalizer.resolveDiarized([
              new SpeakerTurnSegment(0, 2_000, 0),
              new SpeakerTurnSegment(2_100, 4_000, 1),
            ], 0.35, (_samples, speaker) => speaker === 0 ? 0.40 : 0.30, true);

            assert.equal(split, undefined);
            assert.match(finalizer.lastResolutionReason(), /diarization-score-margin/);
            """
        )

    def test_late_sequential_boundary_allows_a_conservative_prefix(self) -> None:
        self.run_finalizer(
            """
            const samples = new Float32Array(72_000);
            samples.fill(0.1);
            const finalizer = new SpeakerTurnFinalizer(16_000, 24_000, 8_000, 2, 72_000);
            finalizer.accept(samples);
            finalizer.observeScore(48_000, 0.60, 0.35);
            finalizer.observeScore(56_000, 0.20, 0.35);
            finalizer.observeScore(64_000, 0.10, 0.35);

            const precise = finalizer.resolveDiarized([
              new SpeakerTurnSegment(0, 52_000, 0),
              new SpeakerTurnSegment(52_000, 72_000, 1),
            ], 0.35, (_samples, speaker) => speaker === 0 ? 0.60 : 0.10);

            assert.equal(precise, undefined);
            assert.equal(finalizer.lastResolutionReason(),
              'diarization-boundary-after-score-transition:52000:not-in:24000-48000');
            const containment = finalizer.resolveContainment();
            assert.ok(containment);
            assert.equal(containment.cutSample, 24_000);
            """
        )

    def test_boundary_is_independent_of_public_pcm_partitioning(self) -> None:
        self.run_finalizer(
            """
            const samples = new Float32Array(3_600);
            for (let i = 0; i < 2_000; i++) samples[i] = i % 2 === 0 ? 0.2 : -0.2;
            for (let i = 2_200; i < samples.length; i++) samples[i] = i % 2 === 0 ? 0.15 : -0.15;

            function cut(partitions) {
              const finalizer = new SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000);
              let offset = 0;
              for (const size of partitions) {
                finalizer.accept(samples.slice(offset, offset + size));
                offset += size;
              }
              finalizer.observeScore(2_000, 0.65, 0.35);
              finalizer.observeScore(3_000, 0.20, 0.35);
              finalizer.observeScore(3_200, 0.10, 0.35);
              return finalizer.resolve([0.3, 1.0, 2.2], 0.35,
                (_samples, start, end) => end <= 2_200 ? 0.60 : start >= 2_200 ? 0.10 : undefined)?.cutSample;
            }

            assert.equal(cut([3_600]), 2_200);
            assert.equal(cut([137, 863, 41, 1_559, 1_000]), 2_200);
            """
        )

    def test_short_target_and_boundary_after_last_positive_window_are_resolved(self) -> None:
        self.run_finalizer(
            """
            const samples = new Float32Array(5_000);
            samples.fill(0.2, 0, 2_000);
            samples.fill(0, 2_000, 2_100);
            samples.fill(0.12, 2_100);
            const finalizer = new SpeakerTurnFinalizer(1_000, 1_500, 500, 2, 5_000);
            finalizer.accept(samples);
            finalizer.observeScore(2_000, 0.62, 0.35);
            finalizer.observeScore(3_000, 0.18, 0.35);
            finalizer.observeScore(3_500, 0.10, 0.35);

            const split = finalizer.resolve([2.1], 0.35,
              (_samples, start, end) => end <= 2_100 ? 0.61 : start >= 2_100 ? 0.09 : undefined);
            assert.ok(split);
            assert.equal(split.cutSample, 2_100);
            """
        )

    def test_strong_hint_waits_for_its_right_context_instead_of_truncating(self) -> None:
        self.run_finalizer(
            """
            const initial = new Float32Array(3_500);
            initial.fill(0.1);
            const finalizer = new SpeakerTurnFinalizer(1_000, 1_500, 500, 2, 10_000);
            finalizer.accept(initial);
            finalizer.observeScore(2_100, 0.60, 0.35);
            finalizer.observeScore(3_000, 0.20, 0.35);
            finalizer.observeScore(3_500, 0.10, 0.35);

            const scorer = (_samples, start, end) =>
              end <= 2_100 ? 0.60 : start >= 2_100 ? 0.10 : undefined;
            const early = finalizer.resolve([2.1], 0.35, scorer);
            assert.equal(early, undefined);
            assert.equal(finalizer.lastResolutionReason(), 'insufficient-refine-context');

            finalizer.accept(new Float32Array(100));
            const resolved = finalizer.resolve([2.1], 0.35, scorer);
            assert.ok(resolved);
            assert.equal(resolved.cutSample, 2_100);
            """
        )

    def test_departure_uses_candidate_context_not_entire_search_band_context(self) -> None:
        self.run_finalizer(
            """
            const samples = new Float32Array(4_200);
            for (let i = 0; i < 2_000; i++) samples[i] = i % 2 === 0 ? 0.2 : -0.2;
            for (let i = 2_200; i < samples.length; i++) samples[i] = i % 2 === 0 ? 0.15 : -0.15;

            const finalizer = new SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000);
            for (let i = 2_000; i < 2_500; i++) samples[i] = i % 2 === 0 ? 0.2 : -0.2;
            samples.fill(0, 2_500, 2_600);
            finalizer.accept(samples.slice(0, 3_700));
            finalizer.observeScore(2_500, 0.65, 0.35);
            finalizer.observeScore(3_500, 0.20, 0.35);
            finalizer.observeScore(3_700, 0.10, 0.35);

            const split = finalizer.resolve([0.3, 1.0, 2.5], 0.35,
              (_samples, start, end) => end <= 2_500 ? 0.60 : start >= 2_500 ? 0.10 : undefined);
            assert.equal(finalizer.needsMoreContext(), false);
            assert.equal(split?.cutSample, 2_500);
            """
        )

    def test_acoustic_resolver_scans_transition_instead_of_trusting_one_late_valley(self) -> None:
        self.run_finalizer(
            """
            const samples = new Float32Array(5_000);
            samples.fill(0.2, 0, 2_000);
            samples.fill(0.12, 2_000);
            // A later quiet patch is not the speaker boundary. The previous implementation picked
            // it once, obtained a contaminated left score, then failed open.
            samples.fill(0, 2_750, 2_900);

            const finalizer = new SpeakerTurnFinalizer(1_000, 1_000, 250, 2, 10_000);
            finalizer.accept(samples);
            finalizer.observeScore(2_500, 0.60, 0.35);
            finalizer.observeScore(3_000, 0.20, 0.35);
            finalizer.observeScore(3_250, 0.10, 0.35);

            let scoreCalls = 0;
            const split = finalizer.resolve([], 0.35, (_samples, start, end) => {
              scoreCalls += 1;
              if (end <= 2_000) return 0.62;
              if (start >= 2_000) return 0.08;
              return 0.20;
            });
            assert.ok(split);
            assert.equal(split.cutSample, 2_000);
            assert.ok(scoreCalls <= 4, `speaker scorer calls must be bounded, got ${scoreCalls}`);
            assert.match(finalizer.lastResolutionReason(), /candidate=2000/);
            """
        )

    def test_ambiguous_boundaries_do_not_claim_a_precise_split(self) -> None:
        self.run_finalizer(
            """
            const continuous = new Float32Array(3_600);
            for (let i = 0; i < continuous.length; i++) continuous[i] = i % 2 === 0 ? 0.2 : -0.2;

            const oneDip = new SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000);
            oneDip.accept(continuous);
            oneDip.observeScore(2_000, 0.65, 0.35);
            assert.equal(oneDip.observeScore(2_400, 0.20, 0.35), 'below');
            assert.equal(oneDip.resolve([0.3, 1.0, 2.2], 0.35, () => 0.1), undefined);

            const noValley = new SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000);
            noValley.accept(continuous);
            noValley.observeScore(2_000, 0.65, 0.35);
            noValley.observeScore(3_000, 0.20, 0.35);
            noValley.observeScore(3_200, 0.10, 0.35);
            assert.equal(noValley.resolve([0.3, 1.0, 2.2], 0.35, () => 0.1), undefined);

            const contradictory = new SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000);
            const withValley = continuous.slice();
            withValley.fill(0, 2_000, 2_200);
            contradictory.accept(withValley);
            contradictory.observeScore(2_000, 0.65, 0.35);
            contradictory.observeScore(3_000, 0.20, 0.35);
            contradictory.observeScore(3_200, 0.10, 0.35);
            assert.equal(contradictory.resolve([0.3, 1.0, 2.2], 0.35, () => 0.60), undefined);
            """
        )

    def test_ambiguous_sequential_departure_uses_safe_containment_prefix(self) -> None:
        self.run_finalizer(
            """
            const samples = new Float32Array(3_600);
            for (let i = 0; i < samples.length; i++) samples[i] = i % 2 === 0 ? 0.2 : -0.2;

            const finalizer = new SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000);
            finalizer.accept(samples);
            finalizer.observeScore(2_000, 0.65, 0.35);
            finalizer.observeScore(3_000, 0.20, 0.35);
            finalizer.observeScore(3_200, 0.10, 0.35);
            assert.equal(finalizer.resolve([0.3, 1.0, 2.2], 0.35, () => 0.1), undefined);

            const containment = finalizer.resolveContainment();
            assert.ok(containment);
            assert.equal(containment.cutSample, 1_000);
            assert.equal(containment.prefix.length, 1_000);
            assert.equal(containment.suffix.length, 2_600);
            assert.equal(finalizer.lastResolutionReason(), 'containment-safe-prefix:1000');
            """
        )

    def test_containment_requires_a_confirmed_uncapped_departure(self) -> None:
        self.run_finalizer(
            """
            const beforeDeparture = new SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000);
            beforeDeparture.accept(new Float32Array(2_000));
            beforeDeparture.observeScore(2_000, 0.65, 0.35);
            assert.equal(beforeDeparture.resolveContainment(), undefined);
            assert.equal(beforeDeparture.lastResolutionReason(), 'containment-not-ready');

            const capped = new SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 2_500);
            capped.accept(new Float32Array(3_000));
            capped.observeScore(2_000, 0.65, 0.35);
            capped.observeScore(2_200, 0.20, 0.35);
            capped.observeScore(2_400, 0.10, 0.35);
            assert.equal(capped.resolveContainment(), undefined);
            assert.equal(capped.lastResolutionReason(), 'containment-buffer-capped');
            """
        )

    def test_containment_cut_is_independent_of_caller_pcm_partitioning(self) -> None:
        self.run_finalizer(
            """
            const samples = new Float32Array(3_600);
            samples.fill(0.2);
            const resolveWithChunks = (chunks) => {
              const finalizer = new SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000);
              let offset = 0;
              for (const size of chunks) {
                finalizer.accept(samples.slice(offset, offset + size));
                offset += size;
              }
              finalizer.observeScore(2_000, 0.65, 0.35);
              finalizer.observeScore(3_000, 0.20, 0.35);
              finalizer.observeScore(3_200, 0.10, 0.35);
              return finalizer.resolveContainment();
            };
            const whole = resolveWithChunks([3_600]);
            const framed = resolveWithChunks([320, 160, 640, 80, 1_000, 1_400]);
            assert.ok(whole);
            assert.ok(framed);
            assert.equal(whole.cutSample, framed.cutSample);
            assert.deepEqual(Array.from(whole.prefix), Array.from(framed.prefix));
            assert.deepEqual(Array.from(whole.suffix), Array.from(framed.suffix));
            """
        )

    def test_sequential_classification_remains_pending_while_refine_context_arrives(self) -> None:
        self.run_finalizer(
            """
            const finalizer = new SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000);
            finalizer.deferResolution(
              'sequential-boundary-ambiguous:diarization-boundary-after-score-transition:3200:not-in:1000-3000:insufficient-refine-context');
            assert.equal(finalizer.needsMoreContext(), true);
            """
        )

    def test_runtime_contains_sequential_ambiguity_but_preserves_overlap_scope(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        containment = source.split("private canContainSpeakerTurn", 1)[1].split(
            "private resolveSpeakerTurnSplit", 1
        )[0]
        self.assertIn("unresolvedReason.startsWith('sequential-boundary-ambiguous:')", containment)
        self.assertIn("isSpeakerTurnSegmentationModelLoaded()", containment)
        resolver = source.split("private resolveSpeakerTurnContainment", 1)[1].split(
            "private canContainSpeakerTurn", 1
        )[0]
        self.assertIn("if (!this.canContainSpeakerTurn(unresolvedReason)) return undefined", resolver)
        self.assertIn("finalizer.resolveContainment()", resolver)
        precise_resolver = source.split("private resolveSpeakerTurnSplit", 1)[1].split(
            "private replaySpeakerSuffix", 1
        )[0]
        self.assertIn(
            "diarizationReason.startsWith('diarization-boundary-after-score-transition:')",
            precise_resolver,
        )
        self.assertNotIn(
            "acousticSplit !== undefined || finalizer.needsMoreContext()",
            precise_resolver,
        )
        self.assertIn(
            "`sequential-boundary-ambiguous:${diarizationReason}:${acousticReason}`",
            precise_resolver,
        )

        finalizer_source = FINALIZER.read_text(encoding="utf-8")
        context_gate = finalizer_source.split("needsMoreContext(): boolean", 1)[1].split(
            "hasPendingDeparture", 1
        )[0]
        self.assertIn("this.resolutionReason.endsWith(':insufficient-refine-context')", context_gate)

        departure = source.split("if (state === 'departure'", 1)[1].split(
            "private speakerVadScoreScheduler", 1
        )[0]
        reject_index = departure.index("this.svRejectCurrentUtterance = true")
        endpoint_index = departure.index("this.triggerSpeakerVadEndpoint()", reject_index)
        self.assertLess(reject_index, endpoint_index)

        rejected_final = source.split("if (speakerVadReject)", 1)[1].split(
            "const targetConfig", 1
        )[0]
        self.assertIn("result.text = '';", rejected_final)
        self.assertIn("result.tokens = [];", rejected_final)
        self.assertIn("result.timestamps = [];", rejected_final)
        self.assertIn("result.tokenConfidences = [];", rejected_final)

    def test_speaker_vad_preserves_requested_partials_while_final_stays_gated(self) -> None:
        source = SPEECH_RECOGNIZE_SDK.read_text(encoding="utf-8")
        start = source.split("const verify = strictBooleanParam", 1)[1].split(
            "this.policeFinalSession =", 1
        )[0]
        self.assertIn(
            "this.partialRequested = params.extraParams['enablePartialResult'] !== false;",
            start,
        )
        self.assertIn("this.partialEnabled = this.partialRequested;", start)
        runtime_toggle = source.split("setSpeakerVadEnabled(enabled: boolean)", 1)[1].split(
            "finish(sessionId: string)", 1
        )[0]
        self.assertNotIn("if (enabled) this.partialEnabled = false;", runtime_toggle)
        self.assertNotIn("this.partialRequested && !enabled", runtime_toggle)

        android = ANDROID_DINGQIAO_ENGINE.read_text(encoding="utf-8")
        self.assertIn("partialRequested = DingqiaoEngineConfig.enablePartialResult(params)", android)
        self.assertIn("enablePartial = partialRequested", android)
        self.assertNotIn("if (enabled) enablePartial = false", android)
        self.assertNotIn("partialRequested && !enabled", android)
        self.assertIn("val speakerVadBeforeToggle = speakerVadEnabled", android)
        self.assertIn(
            "speakerVadEnabled = if (disabled) false else speakerVadBeforeToggle",
            android,
        )
        self.assertIn("enablePartial = partialRequested", android)
        dispatch = android.split("private fun dispatchResult(", 1)[1].split(
            "private fun resultPayload(", 1
        )[0]
        self.assertIn("if (!isFinal && !enablePartial) return@execute", dispatch)

        harmony_decode = RUNTIME.read_text(encoding="utf-8").split(
            "private processDecodedResult(", 1
        )[1].split("private dispatchFinal(", 1)[0]
        self.assertNotIn("this.speakerVadEnabled && !this.svTargetConfirmed", harmony_decode)

        android_core = ANDROID_SESSION_IMPL.read_text(encoding="utf-8")
        post_partial = android_core.split("private fun postPartial(", 1)[1].split(
            "private fun postFinalToProcessor(", 1
        )[0]
        self.assertNotIn("speakerVadEnabled && !svTargetConfirmed", post_partial)


if __name__ == "__main__":
    unittest.main()
