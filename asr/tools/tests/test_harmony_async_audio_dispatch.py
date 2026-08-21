import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DISPATCHER = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SessionAudioDispatcher.ts"
)
ADAPTER = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
)
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"
ADAPTER_ENDPOINT_POLICY = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/EndpointRulePolicy.ts"
)
SHERPA_PATCH = (
    REPO_ROOT
    / "third_party/patches/sherpa-amphion/0013-feat-harmony-decode-online-streams-asynchronously.patch"
)
DEVICE_STRESS = (
    REPO_ROOT
    / "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/util/DeviceStressTest.ets"
)


class HarmonyAsyncAudioDispatchTest(unittest.TestCase):
    def run_dispatcher(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ SessionAudioDispatcher }} from {DISPATCHER.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_write_returns_before_processing_and_snapshots_pcm(self) -> None:
        self.run_dispatcher(
            """
            const events = [];
            let releaseWrite;
            const blocked = new Promise(resolve => { releaseWrite = resolve; });
            const dispatcher = new SessionAudioDispatcher({
              write: async frame => {
                events.push(`write-start-${new Uint8Array(frame)[0]}`);
                await blocked;
                events.push(`write-end-${new Uint8Array(frame)[0]}`);
              },
              finish: async () => events.push('finish'),
            }, message => events.push(`error-${message}`));

            const frame = Uint8Array.from([7, 8]).buffer;
            assert.equal(dispatcher.write(frame), true);
            new Uint8Array(frame).fill(0);
            assert.deepEqual(events, []);

            await Promise.resolve();
            await Promise.resolve();
            assert.deepEqual(events, ['write-start-7']);
            releaseWrite();
            await dispatcher.whenIdle();
            assert.deepEqual(events, ['write-start-7', 'write-end-7']);
            """
        )

    def test_frames_and_finish_are_processed_in_submission_order(self) -> None:
        self.run_dispatcher(
            """
            const events = [];
            const dispatcher = new SessionAudioDispatcher({
              write: async frame => events.push(`audio-${new Uint8Array(frame)[0]}`),
              finish: async () => events.push('finish'),
            }, message => events.push(`error-${message}`));

            assert.equal(dispatcher.write(Uint8Array.from([1]).buffer), true);
            assert.equal(dispatcher.write(Uint8Array.from([2]).buffer), true);
            const finished = dispatcher.finish();
            assert.equal(dispatcher.write(Uint8Array.from([3]).buffer), false);
            await finished;
            assert.deepEqual(events, ['audio-1', 'audio-2', 'finish']);
            """
        )

    def test_diagnostic_queue_counters_are_read_only_and_settle(self) -> None:
        self.run_dispatcher(
            """
            let releaseWrite;
            const blocked = new Promise(resolve => { releaseWrite = resolve; });
            const dispatcher = new SessionAudioDispatcher({
              write: async () => { await blocked; },
              finish: async () => {},
            }, () => {});
            dispatcher.write(new ArrayBuffer(640));
            dispatcher.write(new ArrayBuffer(640));
            assert.equal(dispatcher.diagnosticState().audioQueueDepth, 2);
            assert.equal(dispatcher.diagnosticState().maxAudioQueueDepth, 2);
            await Promise.resolve();
            await Promise.resolve();
            assert.equal(dispatcher.diagnosticState().nativeCallsInFlight, 1);
            releaseWrite();
            await dispatcher.whenIdle();
            assert.equal(dispatcher.diagnosticState().audioQueueDepth, 0);
            assert.equal(dispatcher.diagnosticState().nativeCallsInFlight, 0);
            """
        )

    def test_finish_requested_inside_endpoint_callback_is_visible_to_current_result(self) -> None:
        self.run_dispatcher(
            """
            const events = [];
            let finishRequestedAtEndpoint = false;
            let resolveFinished;
            const finished = new Promise(resolve => { resolveFinished = resolve; });
            let dispatcher;
            dispatcher = new SessionAudioDispatcher({
              write: async () => {
                events.push('speech-end');
                dispatcher.finish();
                events.push(finishRequestedAtEndpoint ? 'text-last' : 'text-endpoint');
              },
              writeFloat: async () => {},
              requestFinish: () => {
                finishRequestedAtEndpoint = true;
                events.push('finish-intent');
              },
              finish: async () => {
                if (!finishRequestedAtEndpoint) events.push('empty-last');
                resolveFinished();
              },
            }, message => events.push(`error-${message}`));

            dispatcher.write(new ArrayBuffer(640));
            await finished;
            assert.deepEqual(events, ['speech-end', 'finish-intent', 'text-last']);
            """
        )

    def test_cancel_drops_work_that_has_not_started(self) -> None:
        self.run_dispatcher(
            """
            const events = [];
            const dispatcher = new SessionAudioDispatcher({
              write: async frame => events.push(`audio-${new Uint8Array(frame)[0]}`),
              finish: async () => events.push('finish'),
            }, message => events.push(`error-${message}`));

            dispatcher.write(Uint8Array.from([1]).buffer);
            dispatcher.write(Uint8Array.from([2]).buffer);
            dispatcher.cancel();
            await dispatcher.whenIdle();
            assert.deepEqual(events, []);
            """
        )

    def test_dispatchers_across_engines_share_one_native_execution_queue(self) -> None:
        self.run_dispatcher(
            """
            const events = [];
            let releaseOld;
            const oldBlocked = new Promise(resolve => { releaseOld = resolve; });
            const oldDispatcher = new SessionAudioDispatcher({
              write: async () => {
                events.push('old-start');
                await oldBlocked;
                events.push('old-end');
              },
              writeFloat: async () => {},
              finish: async () => {},
            }, message => events.push(`old-error-${message}`));

            oldDispatcher.write(Uint8Array.from([1]).buffer);
            await Promise.resolve();
            await Promise.resolve();
            oldDispatcher.cancel();
            const replacement = new SessionAudioDispatcher({
              write: async () => events.push('new-write'),
              writeFloat: async () => {},
              finish: async () => {},
            }, message => events.push(`new-error-${message}`));
            replacement.write(Uint8Array.from([2]).buffer);
            await Promise.resolve();
            await Promise.resolve();
            assert.deepEqual(events, ['old-start']);

            releaseOld();
            await replacement.whenIdle();
            assert.deepEqual(events, ['old-start', 'old-end', 'new-write']);
            """
        )

    def test_throwing_error_callback_does_not_stall_shared_execution_queue(self) -> None:
        self.run_dispatcher(
            """
            const failed = new SessionAudioDispatcher({
              write: async () => { throw new Error('decode failed'); },
              writeFloat: async () => {},
              finish: async () => {},
            }, () => { throw new Error('consumer failed'); });

            assert.equal(failed.write(Uint8Array.from([1]).buffer), true);
            await failed.whenIdle();

            const events = [];
            const replacement = new SessionAudioDispatcher({
              write: async () => events.push('replacement-write'),
              writeFloat: async () => {},
              finish: async () => {},
            }, message => events.push(`replacement-error-${message}`));
            assert.equal(replacement.write(Uint8Array.from([2]).buffer), true);
            await replacement.whenIdle();
            assert.deepEqual(events, ['replacement-write']);
            """
        )

    def test_float_audio_is_snapshotted_and_uses_the_same_fifo(self) -> None:
        self.run_dispatcher(
            """
            const events = [];
            const dispatcher = new SessionAudioDispatcher({
              write: async () => {},
              writeFloat: async samples => events.push(`float-${samples[0]}`),
              finish: async () => events.push('finish'),
            }, message => events.push(`error-${message}`));

            const samples = Float32Array.from([0.25]);
            assert.equal(dispatcher.writeFloat(samples), true);
            samples[0] = 0.75;
            await dispatcher.finish();
            assert.deepEqual(events, ['float-0.25', 'finish']);
            """
        )

    def test_adapter_and_core_use_the_async_decode_path(self) -> None:
        adapter = ADAPTER.read_text(encoding="utf-8")
        runtime = RUNTIME.read_text(encoding="utf-8")
        self.assertIn("from './SessionAudioDispatcher'", adapter)
        self.assertIn("session.acceptPcmBytesAsync(audio)", adapter)
        self.assertNotIn("session.acceptPcmBytes(audio)", adapter)
        self.assertIn("session.acceptPcmFloatAsync(samples)", adapter)
        self.assertNotIn("session.acceptPcmFloat(samples)", adapter)
        self.assertNotIn("session.stop();", adapter)
        dispatcher = DISPATCHER.read_text(encoding="utf-8")
        self.assertIn("static executionTail", dispatcher)
        self.assertIn("async acceptPcmBytesAsync", runtime)
        self.assertIn("await this.recognizer.decodeAsync(this.stream)", runtime)

    def test_adapter_bridges_finish_intent_to_the_current_core_callback(self) -> None:
        adapter = ADAPTER.read_text(encoding="utf-8")
        runtime = RUNTIME.read_text(encoding="utf-8")
        self.assertIn("requestFinish:", adapter)
        self.assertIn("session.requestStopFromCallback()", adapter)
        self.assertIn("requestStopFromCallback(): boolean", runtime)

    def test_dingqiao_endpoint_rule_is_configurable_per_session(self) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ endpointMaxUtteranceSec, endpointRecognizerConfigKey }} from {ADAPTER_ENDPOINT_POLICY.as_uri()!r};

            assert.equal(endpointMaxUtteranceSec({{}}), 20);
            assert.equal(endpointMaxUtteranceSec({{ endpointMaxUtteranceMs: 60000 }}), 60);
            assert.equal(endpointMaxUtteranceSec({{ endpointMaxUtteranceMs: '45000' }}), 45);
            assert.equal(endpointMaxUtteranceSec({{ endpointMaxUtteranceMs: Number.NaN }}), 20);
            assert.equal(endpointMaxUtteranceSec({{ endpointMaxUtteranceMs: 0 }}), 20);
            assert.notEqual(
              endpointRecognizerConfigKey(false, false, {{ endpointMaxUtteranceMs: 20000 }}),
              endpointRecognizerConfigKey(false, false, {{ endpointMaxUtteranceMs: 60000 }}),
            );
            """
        )
        subprocess.run(
            [
                "node",
                "--experimental-strip-types",
                "--experimental-loader",
                str(REPO_ROOT / "asr/tools/tests/ts_extension_loader.mjs"),
                "--input-type=module",
                "-e",
                script,
            ],
            check=True,
            cwd=REPO_ROOT,
        )

        adapter = ADAPTER.read_text(encoding="utf-8")
        self.assertIn("config.endpointRules.rule3MinUtteranceLengthSec =", adapter)
        self.assertIn("endpointMaxUtteranceSec(startParams?.extraParams ?? {})", adapter)
        self.assertIn("endpointRecognizerConfigKey(withTargetSpeaker, withSpeakerVad", adapter)

    def test_native_async_decode_retains_recognizer_and_stream_lifetimes(self) -> None:
        patch = SHERPA_PATCH.read_text(encoding="utf-8")
        self.assertIn("DecodeOnlineStreamAsyncWorker", patch)
        self.assertIn("decodeOnlineStreamAsync", patch)
        self.assertIn("std::shared_ptr<OnlineRecognizerState>", patch)
        self.assertIn("std::shared_ptr<OnlineStreamState>", patch)
        self.assertIn("recognizer_handle->Lease()", patch)
        self.assertIn("stream_handle->Lease()", patch)

    def test_empty_endpoint_restarts_the_stream_instead_of_retaining_encoder_cache(self) -> None:
        runtime = RUNTIME.read_text(encoding="utf-8")
        start = runtime.index("private restartStreamAfterUtterance(reason: string")
        end = runtime.index("private hardRestartStream(reason: string)", start)
        restart = runtime[start:end]

        self.assertIn("this.hardRestartStream(reason);", restart)
        self.assertNotIn("this.recognizer.reset(this.stream);", restart)
        self.assertNotIn("this.recognizer.getResult(this.stream)", restart)

    def test_runtime_logs_endpoint_suppression_and_stream_identity(self) -> None:
        runtime = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("kind=ENDPOINT", runtime)
        self.assertIn("source=native", runtime)
        self.assertIn("source=vad-active", runtime)
        self.assertIn("source=speaker-vad", runtime)
        self.assertIn("kind=RESULT_SUPPRESSED", runtime)
        self.assertIn("kind=STREAM_TRANSITION", runtime)
        self.assertIn("streamGeneration", runtime)
        self.assertIn("action=hard-restart", runtime)
        self.assertIn("action=soft-reset", runtime)

    def test_device_gate_measures_write_audio_call_latency(self) -> None:
        stress = DEVICE_STRESS.read_text(encoding="utf-8")
        self.assertIn("writeBatchElapsedMs", stress)
        self.assertIn("maxWriteCallMs", stress)
        self.assertIn("onstart-write-blocked", stress)


if __name__ == "__main__":
    unittest.main()
