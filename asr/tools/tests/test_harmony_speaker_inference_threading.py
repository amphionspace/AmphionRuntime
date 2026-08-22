import re
import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"
SPEAKER_PATCH = (
    REPO_ROOT
    / "third_party/patches/sherpa-amphion/"
    "0019-feat-harmony-compute-speaker-embeddings-asynchronously.patch"
)
TURN_NATIVE = REPO_ROOT / "asr/harmony/sdk/src/main/cpp/speaker_turn_segmenter.cpp"
LANE = (
    REPO_ROOT
    / "asr/harmony/sdk/src/main/ets/com/amphion/asr/SpeakerInferenceLane.ts"
)
REENTRY_QUEUE = (
    REPO_ROOT
    / "asr/harmony/sdk/src/main/ets/com/amphion/asr/SessionReentryQueue.ts"
)
TS_LOADER = REPO_ROOT / "asr/tools/tests/ts_extension_loader.mjs"


def method_body(source: str, name: str) -> str:
    match = re.search(
        rf"\b(?:private|public|protected)\s+(?:async\s+)?{name}\s*\([^)]*\)[^{{]*\{{",
        source,
    )
    if match is None:
        match = re.search(
            rf"^\s{{2}}(?:async\s+)?{name}\s*\([^)]*\)[^{{]*\{{",
            source,
            re.MULTILINE,
        )
    if match is None:
        raise AssertionError(f"method {name} not found")
    start = match.end()
    depth = 1
    index = start
    while index < len(source) and depth:
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
        index += 1
    if depth != 0:
        raise AssertionError(f"method {name} has unbalanced braces")
    return source[start : index - 1]


class HarmonySpeakerInferenceThreadingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = RUNTIME.read_text(encoding="utf-8")

    def test_native_speaker_inference_has_async_leased_workers(self) -> None:
        speaker_api = SPEAKER_PATCH.read_text(encoding="utf-8")
        speaker_native = speaker_api
        turn_native = TURN_NATIVE.read_text(encoding="utf-8")
        self.assertIn("computeAsync(stream: OnlineStream)", speaker_api)
        self.assertIn("SpeakerEmbeddingExtractorComputeAsyncWorker", speaker_native)
        self.assertIn("extractor_handle->Lease()", speaker_native)
        self.assertIn("stream_handle->Lease()", speaker_native)
        self.assertIn("ProcessAsync", turn_native)
        self.assertIn("context->model = g_model", turn_native)

    def test_slow_inference_lane_is_fifo_and_vad_clock_is_independent(self) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ SpeakerInferenceLane }} from {LANE.as_uri()!r};

            const lane = new SpeakerInferenceLane();
            const generation = lane.generation();
            const applied = [];
            const scorerStartedMs = Date.now();
            const fourSecondScorer = new Promise(resolve => setTimeout(resolve, 4000));
            let audioClockMs = 0;
            let endpointAudioMs = -1;
            for (let i = 0; i < 16; i++) {{
              audioClockMs += 100;
              if (audioClockMs >= 1600 && endpointAudioMs < 0) endpointAudioMs = audioClockMs;
              if (audioClockMs >= 1500) {{
                const deadline = audioClockMs;
                lane.submit(generation, async () => {{
                  await fourSecondScorer;
                  return deadline;
                }}, value => applied.push(value));
              }}
            }}
            assert.equal(endpointAudioMs, 1600, 'trailing silence moved off the PCM clock');
            assert.equal(applied.length, 0, 'PCM/VAD loop waited for the four-second scorer');
            await lane.drain(generation);
            assert.ok(Date.now() - scorerStartedMs >= 3900, 'scorer was not actually slow');
            assert.deepEqual(applied, [1500, 1600]);

            lane.submit(generation, async () => 1700, value => applied.push(value));
            lane.invalidate();
            await lane.drain();
            assert.deepEqual(applied, [1500, 1600]);
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

    def test_lane_quiescence_waits_across_invalidation(self) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ SpeakerInferenceLane }} from {LANE.as_uri()!r};

            const lane = new SpeakerInferenceLane();
            const generation = lane.generation();
            let releaseTask;
            const blocked = new Promise(resolve => {{ releaseTask = resolve; }});
            lane.submit(generation, async () => {{
              await blocked;
              return 7;
            }}, () => {{ throw new Error('invalidated work must not apply'); }});
            lane.invalidate();
            let idle = false;
            const quiescent = lane.whenIdle().then(() => {{ idle = true; }});
            await Promise.resolve();
            assert.equal(idle, false, 'invalidation must not pretend native work is quiescent');
            releaseTask();
            await quiescent;
            assert.equal(lane.pending(), 0);
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

    def test_reentrant_async_queue_preserves_fifo_without_sync_finish(self) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ SessionReentryQueue }} from {REENTRY_QUEUE.as_uri()!r};

            const queue = new SessionReentryQueue();
            const events = [];
            queue.enqueueAudio(new Float32Array([1]));
            queue.enqueueStop();
            await queue.drainAsync(
              () => false,
              async samples => {{
                await Promise.resolve();
                events.push(`audio:${{samples[0]}}`);
              }},
              async () => {{
                await Promise.resolve();
                events.push('stop');
              }});
            assert.deepEqual(events, ['audio:1', 'stop']);
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
    def test_async_public_final_does_not_synchronously_enter_speaker_onnx(self) -> None:
        drain = method_body(self.runtime, "processDecodedResultAsync")
        drain_lane = method_body(self.runtime, "drainSpeakerInferenceAsync")
        prepare = method_body(self.runtime, "prepareVadEndpointSpeakerScoreAsync")
        probe = method_body(self.runtime, "probeInitialSpeechAtTimeoutAsync")
        score = method_body(self.runtime, "scoreSamplesAsync")
        self.assertIn("await this.drainSpeakerInferenceAsync", drain)
        self.assertIn("await this.speakerInferenceLane.drain", drain_lane)
        self.assertIn("await this.prepareVadEndpointSpeakerScoreAsync", drain)
        self.assertIn("await this.scoreSamplesAsync", prepare)
        self.assertIn("await this.prepareVadEndpointSpeakerScoreAsync", probe)
        self.assertIn("await extractor.computeAsync", score)
        self.assertNotIn(".compute(", score)

    def test_speaker_vad_only_final_is_prepared_asynchronously(self) -> None:
        prepare = method_body(self.runtime, "prepareVadEndpointSpeakerScoreAsync")
        dispatch = method_body(self.runtime, "dispatchFinal")
        self.assertIn("this.speakerVadEnabled", prepare)
        self.assertIn("this.svCleanPrefixSpeakerScore", dispatch)
        self.assertIn("!speakerScorePrepared", dispatch)

    def test_async_score_is_pure_until_current_generation_applies_it(self) -> None:
        score = method_body(self.runtime, "scoreSamplesAsync")
        apply_current = method_body(self.runtime, "syncSpeakerTurnState")
        self.assertNotIn("this.lastSpeakerVadScore =", score)
        self.assertIn("this.lastSpeakerVadScore =", apply_current)

    def test_close_retains_runtime_lease_until_speaker_lane_is_idle(self) -> None:
        close = method_body(self.runtime[self.runtime.index("export class AsrSession") :], "close")
        release = method_body(self.runtime, "releaseStreamIfClosed")
        self.assertIn("this.speakerInferenceLane.whenIdle()", self.runtime)
        self.assertIn("this.speakerInferenceLane.pending()", release)
        self.assertIn("this.svInferenceLoopActive = false", close)
        self.assertIn("this.svQueuedInference = undefined", close)

    def test_async_reentry_uses_async_audio_and_finish_paths(self) -> None:
        accept = method_body(self.runtime, "acceptPcmFloatNowAsync")
        finish = method_body(self.runtime, "stopNowAsync")
        drain = method_body(self.runtime, "drainReentryQueueAsync")
        self.assertIn("await this.drainReentryQueueAsync()", accept)
        self.assertIn("await this.drainReentryQueueAsync()", finish)
        self.assertIn("this.acceptPcmFloatNowAsync(samples)", drain)
        self.assertIn("this.stopNowAsync()", drain)

    def test_sync_public_entrypoints_enqueue_the_async_runtime_path(self) -> None:
        accept = method_body(self.runtime, "acceptPcmFloat")
        stop = method_body(self.runtime, "stop")
        enqueue = method_body(self.runtime, "schedulePublicOperation")
        self.assertIn("this.schedulePublicOperation", accept)
        self.assertIn("this.acceptPcmFloatNowAsync", accept)
        self.assertNotIn("this.acceptPcmFloatNow(samples)", accept)
        self.assertIn("this.schedulePublicOperation", stop)
        self.assertIn("this.stopNowAsync", stop)
        self.assertNotIn("this.stopNow()", stop)
        self.assertIn("this.publicOperationTail.then", enqueue)

        accept_async = method_body(self.runtime, "acceptPcmFloatAsync")
        stop_async = method_body(self.runtime, "stopAsync")
        self.assertIn("await this.schedulePublicOperation", accept_async)
        self.assertIn("await this.schedulePublicOperation", stop_async)

    def test_initial_silence_boundary_is_confirmed_after_current_asr_slice(self) -> None:
        feed = method_body(self.runtime, "feedChunkAndDecodeAsync")
        decode = feed.index("await this.feedRecognizerAsync")
        timeout = feed.index("vadAdvance.initialSilenceTimedOut")
        probe = feed.index("await this.probeInitialSpeechAtTimeoutAsync")
        self.assertLess(decode, timeout)
        self.assertLess(timeout, probe)

    def test_native_endpoint_is_announced_before_waiting_for_speaker_inference(self) -> None:
        process = method_body(self.runtime, "processDecodedResultAsync")
        self.assertIn("!isFinal && !isLastFinal", process)
        announce = process.index(
            "this.announceNativeEndpoint(endpointReason, endpointTransition)"
        )
        drain = process.index("await this.drainSpeakerInferenceAsync()")
        finalize = process.index("await this.finalizeAnnouncedVadEndpointAsync")
        self.assertLess(announce, drain)
        self.assertLess(drain, finalize)

    def test_native_endpoint_waiting_for_turn_context_releases_audio_dispatcher(self) -> None:
        process = method_body(self.runtime, "processDecodedResultAsync")
        hold = process.index("this.svContextWaitStartedSample >= 0")
        release = process.index("return;", hold)
        drain = process.index("await this.drainSpeakerInferenceAsync()")
        self.assertLess(release, drain)

    def test_async_resolver_checks_generation_after_native_awaits(self) -> None:
        resolver = method_body(self.runtime, "resolveSpeakerTurnSplitAsync")
        score_resolver = method_body(self.runtime, "resolveWithAsyncSpeakerScores")
        self.assertIn("await processSpeakerTurnSegmentationAsync", resolver)
        self.assertIn("if (!isCurrent()) return undefined", resolver)
        self.assertIn("this.scoreSamplesAsync", score_resolver)
        self.assertIn("await Promise.all", score_resolver)
        self.assertIn("if (!isCurrent()) return undefined", score_resolver)

    def test_turn_resolver_batches_independent_speaker_scores(self) -> None:
        score_resolver = method_body(self.runtime, "resolveWithAsyncSpeakerScores")
        self.assertIn("Promise.all", score_resolver)
        self.assertNotIn(
            "await this.scoreSamplesAsync(requests[index])", score_resolver
        )

    def test_clean_prefix_score_overlaps_prefix_decode(self) -> None:
        commit = method_body(self.runtime, "commitCleanSpeakerTurnAsync")
        score = commit.index("this.computeCleanPrefixSpeakerScoreAsync(split)")
        decode = commit.index("this.recognizer.decodeAsync(prefixStream)")
        joined = commit.index("await Promise.all", max(score, decode))
        self.assertLess(score, joined)
        self.assertLess(decode, joined)

    def test_speaker_embedding_worker_releases_lease_when_queue_throws(self) -> None:
        native = SPEAKER_PATCH.read_text(encoding="utf-8")
        start = native.index("SpeakerEmbeddingExtractorComputeEmbeddingAsyncWrapper")
        body = native[start : native.index("static void DestroySpeakerEmbeddingExtractorWrapper", start)]
        self.assertIn("try {", body)
        self.assertIn("worker->Queue();", body)
        self.assertIn("delete worker;", body)
        self.assertIn("deferred.Reject", body)

    def test_async_clean_turn_failure_never_restores_a_closed_stream(self) -> None:
        commit = method_body(self.runtime, "commitCleanSpeakerTurnAsync")
        invalidated = commit.index("if (!isCurrent())", commit.index("decodeAsync(prefixStream)"))
        catch = commit.rindex("catch (e)")
        self.assertIn("prefixStream.close()", commit[invalidated:catch])
        self.assertIn("this.stream = speculativeStream", commit[invalidated:catch])
        self.assertNotIn("this.stream = speculativeStream", commit[catch:])
        self.assertIn("speculativeStream.close()", commit[catch:])

    def test_live_speaker_vad_reset_discards_stale_work_without_closing_session(self) -> None:
        prepare = method_body(self.runtime, "prepareVadEndpointSpeakerScoreAsync")
        commit = method_body(self.runtime, "commitCleanSpeakerTurnAsync")
        vad_endpoint = method_body(self.runtime, "finalizeAnnouncedVadEndpointAsync")
        speaker_endpoint = method_body(self.runtime, "triggerSpeakerVadEndpointAsync")
        finish = method_body(self.runtime, "commitSpeakerTurnAtFinishAsync")
        feed = method_body(self.runtime, "feedChunkAndDecodeAsync")
        self.assertIn("while (!this.callbackGate.isClosed())", prepare)
        self.assertIn("this.speakerInferenceLane.isCurrent(generation)", prepare)
        self.assertNotIn("this.scoreSamples(", prepare)
        self.assertIn("if (!isCurrent()) return false", commit)
        self.assertNotIn("invalidated during async", commit)
        self.assertIn("await this.drainSpeakerInferenceAsync()", finish)
        self.assertIn("await this.drainSpeakerInferenceAsync()", feed)
        for endpoint in (vad_endpoint, speaker_endpoint):
            commit_index = endpoint.index("await this.commitCleanSpeakerTurnAsync")
            prepare_index = endpoint.index(
                "await this.prepareVadEndpointSpeakerScoreAsync", commit_index
            )
            dispatch_index = endpoint.index("this.dispatchFinal", prepare_index)
            self.assertLess(commit_index, prepare_index)
            self.assertLess(prepare_index, dispatch_index)

    def test_turn_segmenter_async_worker_checks_napi_status(self) -> None:
        native = TURN_NATIVE.read_text(encoding="utf-8")
        start = native.index("napi_value ProcessAsync(")
        process = native[start : native.index("\n}\n\n}  // namespace", start) + 2]
        self.assertIn("napi_status status", process)
        self.assertIn("napi_create_promise", process)
        self.assertIn("napi_create_async_work", process)
        self.assertIn("napi_queue_async_work", process)
        self.assertIn("napi_ok", process)
        self.assertRegex(native, r"CompleteProcess\(napi_env env, napi_status status,")
        self.assertRegex(native, r"CompleteLoad\(napi_env env, napi_status status,")

    def test_trailing_silence_vad_does_not_wait_for_speaker_or_decode(self) -> None:
        body = method_body(self.runtime, "feedChunkAndDecodeAsync")
        vad = body.find("advanceVadGate")
        speaker = body.find("enqueueSpeakerVadInference")
        decode = body.find("await this.feedRecognizerAsync")
        self.assertGreaterEqual(vad, 0, "async audio path must advance VAD explicitly")
        self.assertGreaterEqual(speaker, 0, "speaker inference must use its serial lane")
        self.assertGreaterEqual(decode, 0, "async decode call missing")
        self.assertLess(vad, speaker, "trailing-silence VAD waits for speaker inference")
        self.assertLess(vad, decode, "trailing-silence VAD waits for ASR decode")
        self.assertNotIn("await this.enqueueSpeakerVadInference", body)

    def test_speaker_inference_backpressure_coalesces_one_latest_window(self) -> None:
        enqueue = method_body(self.runtime, "enqueueSpeakerVadInference")
        active = enqueue.index("this.svInferenceLoopActive")
        coalesce = enqueue.index("this.svQueuedInference = request", active)
        submit = enqueue.index("this.speakerInferenceLane.submit")
        self.assertLess(active, coalesce)
        self.assertLess(coalesce, submit)
        self.assertIn("decision=coalesce", enqueue)
        self.assertNotIn("reason=inference-backpressure", enqueue)

    def test_async_turn_context_wait_has_the_same_bounded_policy(self) -> None:
        evaluate = method_body(self.runtime, "evaluateSpeakerVadInferenceAsync")
        self.assertIn("waitedSamples < scheduler.hopSamples * 4", evaluate)
        self.assertIn("this.speakerTurnSegmenterUnavailable = true", evaluate)
        self.assertIn("waitedSamples < scheduler.hopSamples * 2", evaluate)
        self.assertIn("decision=await-model", evaluate)
        self.assertIn("decision=await-context", evaluate)

    def test_same_slice_context_wait_keeps_announced_endpoint_pending(self) -> None:
        process = method_body(self.runtime, "processDecodedResultAsync")
        feed = method_body(self.runtime, "feedChunkAndDecodeAsync")
        drain = process.index("await this.drainSpeakerInferenceAsync()")
        context = process.index("this.svContextWaitStartedSample >= 0", drain)
        prepare = process.index("await this.prepareVadEndpointSpeakerScoreAsync()", context)
        self.assertLess(drain, context)
        self.assertLess(context, prepare)
        self.assertIn("!this.pendingVadStopAtEndpoint", process[context:prepare])
        finalize = method_body(self.runtime, "finalizeReadySpeakerEndpointAsync")
        self.assertIn("if (this.vadEndpointPending)", finalize)
        self.assertIn("await this.finalizeAnnouncedVadEndpointAsync()", finalize)
        self.assertLess(
            feed.index("if (!replay && this.svEndpointReady)"),
            feed.index("this.initialSilenceTracker.observeAcousticSamples"),
        )

    def test_async_runtime_path_never_calls_sync_speaker_inference(self) -> None:
        enqueue = method_body(self.runtime, "enqueueSpeakerVadInference")
        resolver = method_body(self.runtime, "resolveSpeakerTurnSplitAsync")
        self.assertNotIn("scoreSamples(", enqueue)
        self.assertNotIn("processSpeakerTurnSegmentation(", resolver)
        self.assertIn("processSpeakerTurnSegmentationAsync(", resolver)

    def test_speaker_inference_lane_never_reads_the_primary_asr_stream(self) -> None:
        acoustic = method_body(self.runtime, "resolveSpeakerTurnAcousticAsync")
        decoded = method_body(self.runtime, "processDecodedResult")
        self.assertNotIn("this.recognizer.getResult(this.stream)", acoustic)
        self.assertIn("this.speculativeTimestampsSnapshot.slice()", acoustic)
        self.assertIn("this.rememberSpeculativeTimestamps", decoded)

    def test_async_endpoint_and_finish_never_enter_sync_clean_decode(self) -> None:
        feed = method_body(self.runtime, "feedChunkAndDecodeAsync")
        finish = method_body(self.runtime, "stopNowAsync")
        endpoint = method_body(self.runtime, "triggerSpeakerVadEndpointAsync")
        ready_endpoint = method_body(self.runtime, "finalizeReadySpeakerEndpointAsync")
        vad_endpoint = method_body(self.runtime, "finalizeAnnouncedVadEndpointAsync")
        commit = method_body(self.runtime, "commitCleanSpeakerTurnAsync")
        replay = method_body(self.runtime, "replaySpeakerSuffixAsync")

        self.assertIn("await this.finalizeReadySpeakerEndpointAsync()", feed)
        self.assertIn("await this.triggerSpeakerVadEndpointAsync()", ready_endpoint)
        self.assertIn("await this.finalizeAnnouncedVadEndpointAsync()", ready_endpoint)
        self.assertIn("await this.commitSpeakerTurnAtFinishAsync()", finish)
        self.assertIn("await this.commitCleanSpeakerTurnAsync", endpoint)
        self.assertIn("await this.commitCleanSpeakerTurnAsync", vad_endpoint)
        self.assertIn("this.recognizer.decodeAsync(prefixStream)", commit)
        self.assertIn("await Promise.all", commit)
        self.assertNotIn("this.recognizer.decode(prefixStream)", commit)
        self.assertIn("await this.replaySpeakerSuffixAsync(split)", commit)
        self.assertIn("await this.drainAsync(true, false, true)", commit)
        self.assertIn("await this.feedChunkAndDecodeAsync", replay)


if __name__ == "__main__":
    unittest.main()
