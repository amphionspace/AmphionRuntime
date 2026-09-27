import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from asr.tools.tests.test_harmony_speaker_inference_threading import method_body


REPO_ROOT = Path(__file__).resolve().parents[3]
QUEUE = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/SessionReentryQueue.ts"
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"


class HarmonySessionReentryQueueTest(unittest.TestCase):
    def test_terminal_endpoint_cannot_restart_native_work_while_callbacks_remain_open(self) -> None:
        source = RUNTIME.read_text()
        signatures = {
            'acceptPcmFloatNow': 'acceptPcmFloatNow(samples: Float32Array): void',
            'acceptPcmFloatNowAsync': 'async acceptPcmFloatNowAsync(samples: Float32Array): Promise<void>',
            'stopNow': 'stopNow(): void',
            'stopNowAsync': 'async stopNowAsync(): Promise<void>',
            'notifyStopped': 'notifyStopped(): void',
            'isInputTerminated': 'isInputTerminated(): boolean',
            'feedAndDecode': 'feedAndDecode(frame: ProcessedAudioFrame): void',
            'feedAndDecodeAsync': 'async feedAndDecodeAsync(frame: ProcessedAudioFrame): Promise<void>',
        }
        methods = '\n'.join(signature + '{' + method_body(source, name) + '}'
                            for name, signature in signatures.items())
        script = """
          import assert from 'node:assert/strict';
          class AsrError extends Error {}
          const AsrErrorCode={NATIVE_CRASH:1};
          const SPEAKER_FINAL_TAIL_MIN_PADDING_MS=0;
          const INITIAL_DECISION_CHUNK_SAMPLES=2;
          class Session {
            closed=false;stoppedNotified=false;stopNotificationPending=false;
            streamCallDepth=0;liveStreams=1;firstPcmMs=-1;pcmBytesAccepted=0;totalPcmBytes=0;
            speakerVadEnabled=false;pendingSpeakerFinals=[];events=[];
            callbackGate={isClosed:()=>this.closed,invoke:fn=>fn()};
            callback={onSessionStopped:()=>this.events.push('stopped'),onError:e=>{throw e;}};
            stream={inputFinished:()=>this.events.push('input-finished')};
            initialSilenceTracker={hasTimedOut:()=>false,isArmed:()=>true};
            agcIngress={accept:(pcm,fn)=>fn({raw:pcm,processed:pcm}),
              acceptAsync:async(pcm,fn)=>await fn({raw:pcm,processed:pcm}),
              flush:()=>{},flushAsync:async()=>{}};
            feedChunkAndDecode(pcm){
              this.events.push(Array.from(pcm));if(this.terminalAtNextChunk)this.notifyStopped();
            }
            async feedChunkAndDecodeAsync(pcm){this.feedChunkAndDecode(pcm);}
            commitSpeakerTurnAtFinish(){return false;}
            async commitSpeakerTurnAtFinishAsync(){return false;}
            flushAdaptiveFinalTail(){this.events.push('tail');return 1;}
            async flushAdaptiveFinalTailAsync(){
              this.events.push('tail');if(this.tailWait)await this.tailWait;return 1;
            }
            drain(){this.events.push('last');}
            async drainAsync(){this.drain();}
            drainReentryQueue(){}
            async drainReentryQueueAsync(){}
            releaseStreamIfClosed(){if(this.closed&&this.streamCallDepth===0)this.liveStreams=0;}
            close(){this.closed=true;this.releaseStreamIfClosed();}
        """ + methods + """
          }
          // Same terminal endpoint, with diarization or a deferred speaker score still pending.
          for(const pendingScore of [false,true]) {
            for(const asynchronous of [true,false]) {
              const session=new Session();
              session.pendingSpeakerFinals=pendingScore?[{}]:[];
              session.notifyStopped();
              const terminalEvents=session.events.slice();
              let release;session.tailWait=new Promise(resolve=>release=resolve);
              const work=asynchronous?session.stopNowAsync():session.stopNow();
              await Promise.resolve();await Promise.resolve();
              // Complete the independent diarization task while an old implementation would
              // still be in its redundant native tail decode.
              session.close();
              assert.equal(session.liveStreams,0,'terminal endpoint restarted native work');
              release();await work;
              assert.deepEqual(session.events,terminalEvents);
              const late=new Session();late.pendingSpeakerFinals=pendingScore?[{}]:[];
              late.notifyStopped();const before=late.events.slice();
              if(asynchronous)await late.acceptPcmFloatNowAsync(new Float32Array([1,2]));
              else late.acceptPcmFloatNow(new Float32Array([1,2]));
              assert.deepEqual(late.events,before,'PCM after terminal boundary reached native');
              assert.equal(late.totalPcmBytes,0,'late PCM changed the committed audio clock');
              // The input guard must not close callbacks or discard pending scoring results.
              assert.equal(late.closed,false);
              assert.equal(late.pendingSpeakerFinals.length,pendingScore?1:0);
              if(pendingScore){late.pendingSpeakerFinals=[];late.notifyStopped();}
              assert.equal(late.events.filter(e=>e==='stopped').length,1);
            }
          }
          // Non-terminal input and its single normal finish retain ordering in both paths.
          for(const asynchronous of [false,true]) {
            const session=new Session();
            for(const pcm of [new Float32Array([1]),new Float32Array([2,3])]) {
              if(asynchronous)await session.acceptPcmFloatNowAsync(pcm);
              else session.acceptPcmFloatNow(pcm);
            }
            if(asynchronous){await session.stopNowAsync();await session.stopNowAsync();}
            else {session.stopNow();session.stopNow();}
            assert.deepEqual(session.events,[[1],[2,3],'tail','input-finished','last','stopped']);
            assert.equal(session.totalPcmBytes,6);
          }
          // The terminal boundary also holds inside one large input buffer and during AGC flush.
          for(const asynchronous of [false,true]) {
            for(const split of [false,true]) {
              const session=new Session();session.terminalAtNextChunk=true;
              const frames=split?[[1,2],[3,4]]:[[1,2,3,4]];
              for(const frame of frames) {
                if(asynchronous)await session.acceptPcmFloatNowAsync(new Float32Array(frame));
                else session.acceptPcmFloatNow(new Float32Array(frame));
              }
              assert.deepEqual(session.events,[[1,2],'stopped']);
            }
            const flushing=new Session();
            flushing.agcIngress.flush=()=>flushing.notifyStopped();
            flushing.agcIngress.flushAsync=async()=>flushing.notifyStopped();
            if(asynchronous)await flushing.stopNowAsync();else flushing.stopNow();
            assert.deepEqual(flushing.events,['stopped'],'flush already consumed the terminal stop');
          }
        """
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / 'terminal-input.mts'
            fixture.write_text(script)
            subprocess.run(['node', '--experimental-strip-types', str(fixture)],
                           cwd=REPO_ROOT, check=True)

    def run_queue(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ SessionReentryQueue }} from {QUEUE.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_audio_is_snapshotted_before_callback_returns(self) -> None:
        self.run_queue(
            """
            const queue = new SessionReentryQueue();
            const frame = new Float32Array([0.25, -0.5]);
            const accepted = [];
            queue.enqueueAudio(frame);
            frame.fill(0);
            queue.drain(() => false, samples => accepted.push(Array.from(samples)), () => {});
            assert.deepEqual(accepted, [[0.25, -0.5]]);
            """
        )

    def test_operations_before_stop_keep_order_and_later_audio_is_dropped(self) -> None:
        self.run_queue(
            """
            const queue = new SessionReentryQueue();
            const events = [];
            queue.enqueueAudio(new Float32Array([1]));
            queue.enqueueAudio(new Float32Array([2]));
            queue.enqueueStop();
            queue.enqueueAudio(new Float32Array([3]));
            queue.enqueueStop();
            queue.drain(() => false,
              samples => events.push(`audio-${samples[0]}`),
              () => events.push('stop'));
            assert.deepEqual(events, ['audio-1', 'audio-2', 'stop']);
            """
        )

    def test_callback_reentry_appends_work_without_recursive_drain(self) -> None:
        self.run_queue(
            """
            const queue = new SessionReentryQueue();
            const events = [];
            queue.enqueueAudio(new Float32Array([1]));
            queue.drain(() => false, samples => {
              events.push(samples[0]);
              if (samples[0] === 1) queue.enqueueAudio(new Float32Array([2]));
            }, () => {});
            assert.deepEqual(events, [1, 2]);
            """
        )

    def test_endpoint_consumes_a_synchronous_stop_without_creating_an_empty_stream(self) -> None:
        self.run_queue(
            """
            const queue = new SessionReentryQueue();
            const events = [];
            queue.enqueueStop();
            assert.equal(queue.consumeStopAtEndpoint(), true);
            queue.drain(() => false,
              samples => events.push(`audio-${samples[0]}`),
              () => events.push('stop'));
            assert.deepEqual(events, []);
            """
        )

    def test_endpoint_does_not_skip_audio_queued_before_stop(self) -> None:
        self.run_queue(
            """
            const queue = new SessionReentryQueue();
            const events = [];
            queue.enqueueAudio(new Float32Array([1]));
            queue.enqueueStop();
            assert.equal(queue.consumeStopAtEndpoint(), false);
            queue.drain(() => false,
              samples => events.push(`audio-${samples[0]}`),
              () => events.push('stop'));
            assert.deepEqual(events, ['audio-1', 'stop']);
            """
        )

    def test_runtime_defers_stream_calls_made_inside_callbacks(self) -> None:
        runtime = RUNTIME.read_text(encoding="utf-8")
        self.assertIn("from './SessionReentryQueue'", runtime)
        self.assertIn("this.callbackGate.isInvoking()", runtime)
        self.assertIn("this.reentryQueue.enqueueAudio(samples)", runtime)
        self.assertIn("this.reentryQueue.enqueueStop()", runtime)

    def test_runtime_promotes_the_current_endpoint_when_its_callback_requests_stop(self) -> None:
        runtime = RUNTIME.read_text(encoding="utf-8")
        self.assertIn(
            "const stopAtEndpoint = this.reentryQueue.consumeStopAtEndpoint();",
            runtime,
        )
        self.assertIn(
            "this.dispatchFinal(true, decodeDurationMs, isLastFinal || stopAtEndpoint);",
            runtime,
        )
        self.assertIn("if (stopAtEndpoint)", runtime)


if __name__ == "__main__":
    unittest.main()
