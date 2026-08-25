import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MEETING = ROOT / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/meeting"
SCHEDULER = MEETING / "MeetingWindowScheduler.ts"
REGISTRY = MEETING / "OnlineSpeakerRegistry.ts"
BARRIER = MEETING / "MeetingFinishBarrier.ts"
TIMELINE = MEETING / "MeetingTranscriptState.ts"
CLUSTERER = MEETING / "MeetingGlobalClusterer.ts"
RUNTIME_LEASE = MEETING / "MeetingRuntimeLease.ts"
TURN_NATIVE = ROOT / "asr/harmony/sdk/src/main/cpp/speaker_turn_segmenter.cpp"
TURN_TYPES = ROOT / "asr/harmony/sdk/src/main/cpp/types/libamphion_asr/index.d.ts"
RUNTIME = ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"
CORE_TYPES = ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Types.ets"
PUBLIC_MODELS = ROOT / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/DingqiaoModels.ets"
CHILD_SERVICE = MEETING / "MeetingSpeakerChildService.ets"
PROCESS_CLIENT = MEETING / "MeetingSpeakerProcessClient.ets"
SESSION = MEETING / "MeetingSpeakerSession.ets"
ADAPTER = ROOT / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
TS_LOADER = ROOT / "asr/tools/tests/ts_extension_loader.mjs"


def run_node(script: str) -> None:
    subprocess.run(
        [
            "node",
            "--experimental-strip-types",
            "--experimental-loader",
            TS_LOADER.as_uri(),
            "--input-type=module",
            "-e",
            textwrap.dedent(script),
        ],
        check=True,
        cwd=ROOT,
    )


class HarmonyMeetingSpeakerSessionTest(unittest.TestCase):
    def test_public_meeting_api_is_optional_and_does_not_reuse_asr_last_fields(self) -> None:
        models = PUBLIC_MODELS.read_text(encoding="utf-8")
        for field in ("utteranceId?", "speakerId?", "secondarySpeakerIds?"):
            self.assertIn(field, models)
        self.assertIn("onSpeakerUpdate?", models)
        self.assertIn("onMeetingResult?", models)
        self.assertIn("export class SpeakerUpdate", models)
        self.assertIn("export class MeetingResult", models)
        meeting_result = models.split("export class MeetingResult", 1)[1].split("}", 1)[0]
        self.assertNotIn("isLast", meeting_result)
        self.assertNotIn("isFinal", meeting_result)

    def test_runtime_converts_native_token_times_to_session_global_clock(self) -> None:
        runtime = RUNTIME.read_text(encoding="utf-8")
        core_types = CORE_TYPES.read_text(encoding="utf-8")
        self.assertIn("streamStartSample", runtime)
        self.assertIn("toSessionGlobalTimestamps", runtime)
        self.assertIn("result.rawText =", runtime)
        self.assertIn("rawText: string", core_types)
        self.assertIn("private publicSamplesFed: number = 0", runtime)
        self.assertGreaterEqual(
            runtime.count("this.streamStartSample = this.publicSamplesFed"), 3
        )
        self.assertNotIn(
            "this.streamStartSample = Math.floor(this.totalPcmBytes / 2)", runtime
        )
        self.assertIn("if (!replay) this.publicSamplesFed += rawSamples.length", runtime)

    def test_native_segmentation_preserves_overlap_speaker_mask(self) -> None:
        native = TURN_NATIVE.read_text(encoding="utf-8")
        types = TURN_TYPES.read_text(encoding="utf-8")
        self.assertIn("speaker_mask", native)
        self.assertIn("ClassToSpeakerMask", native)
        self.assertIn('"speakerMask"', native)
        self.assertIn("speakerMask: number", types)

    def test_rejected_speaker_vad_final_redacts_raw_and_processed_text(self) -> None:
        runtime = RUNTIME.read_text(encoding="utf-8")
        rejection = runtime.split("if (speakerVadReject) {", 1)[1].split(
            "if (this.targetSpeakerEnabled)", 1
        )[0]
        self.assertIn("result.rawText = '';", rejection)
        self.assertIn("result.text = '';", rejection)

    def test_all_asr_last_paths_join_the_meeting_finish_barrier(self) -> None:
        adapter = ADAPTER.read_text(encoding="utf-8")
        rejected = adapter.split("handleFinalRejected", 1)[1].split(
            "handleAsrError", 1
        )[0]
        fallback = adapter.split("handleSessionStopped", 1)[1].split(
            "private ensureAlive", 1
        )[0]
        self.assertIn("meetingSpeakerSession.observeAsrFinal(payload, result)", rejected)
        self.assertIn("meetingFinishBarrier?.resolveAsr(payload)", rejected)
        self.assertIn("meetingSpeakerSession.observeAsrFinal(result, asrTail)", fallback)
        self.assertIn("meetingFinishBarrier?.resolveAsr(result)", fallback)

    def test_meeting_initialization_failure_degrades_without_failing_asr_start(self) -> None:
        adapter = ADAPTER.read_text(encoding="utf-8")
        meeting_start = adapter.split(
            "enableMeetingSpeakerSeparation", 1
        )[1].split("publishSession", 1)[0]
        self.assertIn("try {", meeting_start)
        self.assertIn("new DegradedMeetingSpeakerSession", meeting_start)
        self.assertIn("meeting speaker initialization failed", meeting_start)

    def test_child_process_preserves_padded_window_offset_in_result(self) -> None:
        child = CHILD_SERVICE.read_text(encoding="utf-8")
        self.assertGreaterEqual(child.count("contentStartInWindowSample: number"), 2)
        self.assertIn("contentStartInWindowSample: job.contentStartInWindowSample", child)

    def test_spool_failure_is_isolated_from_asr_and_finish(self) -> None:
        client = PROCESS_CLIENT.read_text(encoding="utf-8")
        append_body = client.split("append(audio: ArrayBuffer)", 1)[1].split(
            "finish(): void", 1
        )[0]
        finish_body = client.split("finish(): void", 1)[1].split("cancel(): void", 1)[0]
        self.assertIn("this.fail(`meeting speaker spool failed:", append_body)
        self.assertIn("this.fail(`meeting speaker finish spool failed:", finish_body)
        self.assertIn("this.restartCount = 0", client)
        self.assertIn("process.kill(0, pid)", client)
        self.assertIn("drainTerminationCallbacks", client)
        self.assertIn("client.cleanup((): void => { this.releaseRuntimeLease(); })",
                      SESSION.read_text(encoding="utf-8"))

    def test_caller_session_id_never_participates_in_job_paths(self) -> None:
        client = PROCESS_CLIENT.read_text(encoding="utf-8")
        constructor = client.split("constructor(context:", 1)[1].split(
            "append(audio:", 1
        )[0]
        self.assertIn("/meeting-jobs/job-${Date.now()}-${localJobId}", constructor)
        self.assertNotIn("/meeting-jobs/${sessionId}", constructor)

    def test_segments_crossing_a_stable_boundary_are_clipped_not_dropped(self) -> None:
        session = SESSION.read_text(encoding="utf-8")
        self.assertIn(
            "Math.min(window.realEndSample, window.stableEndSample,", session
        )
        self.assertNotIn("globalEnd > window.stableEndSample", session)
        self.assertIn(
            "Math.min(this.maxSpeakers, clustered.clusterCount)", session
        )

    def test_window_schedule_is_frame_independent_and_finish_flushes_tail(self) -> None:
        run_node(
            f"""
            import assert from 'node:assert/strict';
            import {{ MeetingWindowScheduler }} from {SCHEDULER.as_uri()!r};

            const whole = new MeetingWindowScheduler(16_000);
            const framed = new MeetingWindowScheduler(16_000);
            const wholeWindows = whole.acceptSamples(16_000 * 17);
            const framedWindows = [];
            for (let i = 0; i < 17 * 50; i++) {{
              framedWindows.push(...framed.acceptSamples(320));
            }}
            assert.deepEqual(framedWindows, wholeWindows);
            assert.deepEqual(wholeWindows.map(window => [window.startSample, window.endSample]), [
              [0, 40_000], [0, 80_000], [0, 120_000], [0, 160_000],
              [40_000, 200_000], [80_000, 240_000]
            ]);
            assert.deepEqual(wholeWindows.map(window => window.commitStartSample),
              [0, 16_000, 56_000, 96_000, 136_000, 176_000]);
            assert.equal(wholeWindows[0].stableEndSample, 16_000);
            const tail = whole.finish();
            assert.equal(tail.startSample, 112_000);
            assert.equal(tail.endSample, 272_000);
            assert.equal(tail.realEndSample, 272_000);
            assert.equal(tail.commitStartSample, 216_000);
            assert.equal(tail.stableEndSample, 272_000);
            """
        )

    def test_registry_keeps_ids_stable_and_never_forces_a_fifth_speaker(self) -> None:
        run_node(
            f"""
            import assert from 'node:assert/strict';
            import {{ OnlineSpeakerRegistry }} from {REGISTRY.as_uri()!r};

            const registry = new OnlineSpeakerRegistry(4, 0.72, 0.05);
            const s1 = registry.assign(new Float32Array([1, 0, 0, 0]), 2_000, 2_000);
            const s2 = registry.assign(new Float32Array([0, 1, 0, 0]), 2_000, 4_000);
            assert.equal(s1.speakerId, 'S1');
            assert.equal(s2.speakerId, 'S2');
            assert.equal(registry.assign(new Float32Array([0.99, 0.05, 0, 0]), 1_500, 6_000).speakerId, 'S1');
            assert.equal(registry.assign(new Float32Array([0.03, 0.99, 0, 0]), 1_500, 8_000).speakerId, 'S2');
            assert.equal(registry.assign(new Float32Array([0, 0, 1, 0]), 2_000, 10_000).speakerId, 'S3');
            assert.equal(registry.assign(new Float32Array([0, 0, 0, 1]), 2_000, 12_000).speakerId, 'S4');
            const fifth = registry.assign(new Float32Array([-1, 0, 0, 0]), 2_000, 14_000);
            assert.equal(fifth.speakerId, 'UNKNOWN');
            assert.equal(registry.assign(undefined, 400, 14_400).speakerId, 'UNKNOWN');
            assert.deepEqual(registry.speakerIds(), ['S1', 'S2', 'S3', 'S4']);

            const mutual = new OnlineSpeakerRegistry(3, 0.72, 0.01);
            assert.equal(mutual.assign(new Float32Array([1, 0]), 2_000, 1_000).speakerId, 'S1');
            const batch = mutual.assignBatch([
              new Float32Array([1, 0]), new Float32Array([0.98, 0.2])
            ], [2_000, 2_000], 3_000);
            assert.equal(batch[0].speakerId, 'S1');
            assert.equal(batch[1].speakerId, 'S2');
            """
        )

    def test_global_clusterer_uses_weak_prior_and_maps_back_to_display_ids(self) -> None:
        run_node(
            f"""
            import assert from 'node:assert/strict';
            import {{ MeetingGlobalClusterer }} from {CLUSTERER.as_uri()!r};

            const clusterer = new MeetingGlobalClusterer(4, 2);
            const result = clusterer.cluster([
              {{ embedding: [1, 0], durationMs: 3000, onlineSpeakerId: 'S1' }},
              {{ embedding: [0.98, 0.1], durationMs: 2000, onlineSpeakerId: 'S1' }},
              {{ embedding: [0, 1], durationMs: 2500, onlineSpeakerId: 'S2' }},
              {{ embedding: [0.1, 0.98], durationMs: 1500, onlineSpeakerId: 'S2' }}
            ]);
            assert.deepEqual(result.observationSpeakerIds, ['S1', 'S1', 'S2', 'S2']);
            assert.equal(result.clusterCount, 2);
            assert.deepEqual(result.speakerRemap, {{ S1: 'S1', S2: 'S2' }});

            const crossed = clusterer.cluster([
              {{ embedding: [1, 0], durationMs: 6000, onlineSpeakerId: 'S1' }},
              {{ embedding: [1, 0], durationMs: 5000, onlineSpeakerId: 'S2' }},
              {{ embedding: [0, 1], durationMs: 5000, onlineSpeakerId: 'S1' }}
            ]);
            assert.equal(new Set(crossed.observationSpeakerIds).size, 2);
            assert.notEqual(crossed.observationSpeakerIds[0], crossed.observationSpeakerIds[2]);

            const longMeeting = [];
            for (let i = 0; i < 3000; i++) {{
              longMeeting.push({{
                embedding: i % 2 === 0 ? [1, 0] : [0, 1],
                durationMs: 2000,
                onlineSpeakerId: i % 2 === 0 ? 'S1' : 'S2'
              }});
            }}
            assert.equal(clusterer.cluster(longMeeting).clusterCount, 2);
            """
        )

    def test_finish_barrier_orders_final_callbacks_and_degrades_on_timeout(self) -> None:
        run_node(
            f"""
            import assert from 'node:assert/strict';
            import {{ MeetingFinishBarrier }} from {BARRIER.as_uri()!r};

            const events = [];
            const barrier = new MeetingFinishBarrier(100, result => events.push(result));
            barrier.begin();
            barrier.resolveSpeaker({{ degraded: false, value: 'meeting-final' }});
            assert.deepEqual(events, []);
            barrier.resolveAsr('asr-last');
            assert.deepEqual(events, [{{ asr: 'asr-last', speaker: 'meeting-final', degraded: false }}]);
            barrier.resolveAsr('duplicate');
            assert.equal(events.length, 1);

            const timedOut = [];
            const timeoutBarrier = new MeetingFinishBarrier(20, result => timedOut.push(result));
            timeoutBarrier.begin();
            timeoutBarrier.resolveAsr('tail');
            await new Promise(resolve => setTimeout(resolve, 40));
            assert.deepEqual(timedOut, [{{ asr: 'tail', speaker: undefined, degraded: true }}]);
            timeoutBarrier.resolveSpeaker({{ degraded: false, value: 'late' }});
            assert.equal(timedOut.length, 1);

            const missingAsr = [];
            const missingAsrBarrier = new MeetingFinishBarrier(
              20, result => missingAsr.push(result), () => 'timeout-last');
            missingAsrBarrier.begin();
            await new Promise(resolve => setTimeout(resolve, 40));
            assert.deepEqual(missingAsr, [{{
              asr: 'timeout-last', speaker: undefined, degraded: true
            }}]);
            """
        )

    def test_meeting_runtime_release_waits_for_active_native_work(self) -> None:
        run_node(
            f"""
            import assert from 'node:assert/strict';
            import {{ MeetingRuntimeLeaseRegistry }} from {RUNTIME_LEASE.as_uri()!r};

            const lease = MeetingRuntimeLeaseRegistry.acquire();
            let released = false;
            const waiting = MeetingRuntimeLeaseRegistry.beginRelease().then(() => {{
              released = true;
              MeetingRuntimeLeaseRegistry.endRelease();
            }});
            await new Promise(resolve => setTimeout(resolve, 10));
            assert.equal(released, false);
            assert.throws(() => MeetingRuntimeLeaseRegistry.acquire());
            lease.release();
            await waiting;
            assert.equal(released, true);
            const next = MeetingRuntimeLeaseRegistry.acquire();
            next.release();
            """
        )

    def test_transcript_revision_is_monotonic_and_token_split_conserves_text(self) -> None:
        run_node(
            f"""
            import assert from 'node:assert/strict';
            import {{ MeetingTranscriptState }} from {TIMELINE.as_uri()!r};

            const timeline = new MeetingTranscriptState();
            const id = timeline.addUtterance({{
              rawText: '甲乙丙丁', text: '甲乙丙丁',
              tokens: ['甲', '乙', '丙', '丁'], tokenTimesMs: [200, 700, 1200, 1700],
              beginTime: 0, endTime: 2000
            }});
            assert.equal(id, 'u1');
            const first = timeline.applySpeakerTurns([
              {{ beginTime: 0, endTime: 1000, speakerId: 'S1', secondarySpeakerIds: [] }},
              {{ beginTime: 1000, endTime: 2000, speakerId: 'S2', secondarySpeakerIds: ['S1'] }}
            ]);
            assert.deepEqual(first.map(update => [update.utteranceId, update.revision, update.speakerId]),
              [['u1', 1, 'S1']]);
            assert.deepEqual(timeline.applySpeakerTurns([]), []);
            const split = timeline.finalUtterances();
            assert.equal(split.map(item => item.text).join(''), '甲乙丙丁');
            assert.deepEqual(split.map(item => item.speakerId), ['S1', 'S2']);
            assert.deepEqual(split[1].secondarySpeakerIds, ['S1']);

            const fallback = new MeetingTranscriptState();
            fallback.addUtterance({{
              rawText: '二十三', text: '23', tokens: ['二', '十', '三'],
              tokenTimesMs: [100, 200, 300], beginTime: 0, endTime: 400
            }});
            fallback.applySpeakerTurns([
              {{ beginTime: 0, endTime: 200, speakerId: 'S1', secondarySpeakerIds: [] }},
              {{ beginTime: 200, endTime: 400, speakerId: 'S2', secondarySpeakerIds: [] }}
            ]);
            const unsplit = fallback.finalUtterances();
            assert.equal(unsplit.length, 1);
            assert.equal(unsplit[0].text, '23');

            const recent = new MeetingTranscriptState();
            recent.addUtterance({{
              rawText: '旧', text: '旧', tokens: ['旧'], tokenTimesMs: [100],
              beginTime: 0, endTime: 1000
            }});
            recent.addUtterance({{
              rawText: '新', text: '新', tokens: ['新'], tokenTimesMs: [70100],
              beginTime: 70000, endTime: 71000
            }});
            recent.applySpeakerTurns([
              {{ beginTime: 0, endTime: 1000, speakerId: 'S1', secondarySpeakerIds: [] }},
              {{ beginTime: 70000, endTime: 71000, speakerId: 'S1', secondarySpeakerIds: [] }}
            ]);
            const corrected = recent.applySpeakerRemap({{ S1: 'S2' }}, 11000);
            assert.deepEqual(corrected.map(update => update.utteranceId), ['u2']);
            assert.equal(recent.currentAssignment('u1').speakerId, 'S1');
            assert.equal(recent.currentAssignment('u2').speakerId, 'S2');

            const evidence = new MeetingTranscriptState();
            evidence.addUtterance({{
              rawText: '甲乙', text: '甲乙', tokens: ['甲', '乙'], tokenTimesMs: [250, 750],
              beginTime: 0, endTime: 1000
            }});
            evidence.applySpeakerTurns([
              {{ beginTime: 0, endTime: 500, speakerId: 'S1', secondarySpeakerIds: [],
                 evidenceKey: 'w1:0' }},
              {{ beginTime: 500, endTime: 1000, speakerId: 'S1', secondarySpeakerIds: [],
                 evidenceKey: 'w2:0' }}
            ]);
            evidence.applyEvidenceRemap({{ 'w1:0': 'S1', 'w2:0': 'S2' }});
            assert.deepEqual(evidence.finalUtterances().map(item => item.speakerId), ['S1', 'S2']);
            """
        )


if __name__ == "__main__":
    unittest.main()
