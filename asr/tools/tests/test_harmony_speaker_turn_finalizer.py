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
                str(TS_LOADER),
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

    def test_finish_rejects_replayed_suffix_without_a_confirmed_target(self) -> None:
        self.run_finalizer(
            """
            assert.equal(shouldRejectSpeakerVadFinal(true, true, false), true);
            assert.equal(shouldRejectSpeakerVadFinal(true, false, false), true);
            assert.equal(shouldRejectSpeakerVadFinal(true, false, true), false);
            assert.equal(shouldRejectSpeakerVadFinal(false, true, false), false);
            """
        )

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

    def test_async_lane_commits_speaker_turn_before_speculative_decode(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        async_lane = source.split("private async feedChunkAndDecodeAsync", 1)[1].split(
            "// Acoustic activity only grants", 1
        )[0]
        accept_index = async_lane.index("this.speakerTurnFinalizer(speakerVad).accept(samples)")
        split_index = async_lane.index("this.maybeTriggerSpeakerVadEndpoint(samples.length)")
        decode_index = async_lane.index("await this.feedRecognizerAsync(samples, false)")
        self.assertLess(accept_index, split_index)
        self.assertLess(split_index, decode_index)
        self.assertEqual(1, async_lane.count("this.maybeTriggerSpeakerVadEndpoint(samples.length)"))

    def test_async_finish_commits_a_pending_clean_speaker_turn(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        async_stop = source.split("private async stopNowAsync", 1)[1].split(
            "updateHotwords", 1
        )[0]
        commit_index = async_stop.index("this.commitCleanSpeakerTurn(true, false)")
        speculative_flush_index = async_stop.index("this.appendFinalTailSilence()")
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

    def test_speaker_turn_accuracy_requires_a_real_endpoint_before_finish(self) -> None:
        carrier = DEVICE_STRESS.read_text(encoding="utf-8")
        cycle = carrier.split("async function runSpeakerVadTurnCycle", 1)[1].split(
            "function enableTargetSpeakerEnhancement", 1
        )[0]
        self.assertIn("const speechEndsBeforeFinish = events.speechEnds", cycle)
        self.assertIn("speechEndsBeforeFinish > 0", cycle)
        self.assertIn("speaker-vad-turn-missing-endpoint", cycle)

    def test_c1_diarization_selects_latest_stable_target_to_other_boundary(self) -> None:
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

            assert.ok(split);
            assert.equal(split.cutSample, fixture.expected_cut_sample);
            assert.equal(split.prefix.length, fixture.expected_cut_sample);
            assert.equal(split.suffix.length,
              fixture.total_samples - fixture.expected_cut_sample);
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
              'diarization-outside-score-transition:20000:not-in:24000-48000');
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

    def test_ambiguous_or_non_sequential_boundary_fails_open(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
