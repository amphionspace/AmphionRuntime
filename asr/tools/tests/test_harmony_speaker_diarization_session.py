import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DIARIZATION = ROOT / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/diarization"
SCHEDULER = DIARIZATION / "DiarizationWindowScheduler.ts"
REGISTRY = DIARIZATION / "OnlineSpeakerRegistry.ts"
BARRIER = DIARIZATION / "SpeakerDiarizationFinishBarrier.ts"
TIMELINE = DIARIZATION / "SpeakerDiarizationTranscriptState.ts"
CLUSTERER = DIARIZATION / "SpeakerDiarizationGlobalClusterer.ts"
RUNTIME_LEASE = DIARIZATION / "SpeakerDiarizationRuntimeLease.ts"
TURN_NATIVE = ROOT / "asr/harmony/sdk/src/main/cpp/speaker_turn_segmenter.cpp"
TURN_TYPES = ROOT / "asr/harmony/sdk/src/main/cpp/types/libamphion_asr/index.d.ts"
RUNTIME = ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"
CORE_TYPES = ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Types.ets"
CORE_DIARIZATION = ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/SpeakerDiarizationInference.ets"
PUBLIC_MODELS = ROOT / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/DingqiaoModels.ets"
CONFIG_POLICY = DIARIZATION / "SpeakerDiarizationConfigPolicy.ts"
SPEAKER_INDEX_POLICY = DIARIZATION / "SpeakerDiarizationSpeakerIndex.ts"
LOCAL_CLIENT = DIARIZATION / "SpeakerDiarizationLocalClient.ets"
SESSION = DIARIZATION / "SpeakerDiarizationSession.ets"
ADAPTER = ROOT / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
DEVICE_STRESS = ROOT / (
    "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/util/DeviceStressTest.ets"
)
ENTRY_ABILITY = ROOT / (
    "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/entryability/EntryAbility.ets"
)
DEMO_MANIFEST = ROOT / "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/module.json5"
PUBLIC_DOC = ROOT / "delivery/harmony-dingqiao/docs/语音识别SDK接口.md"
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


class HarmonySpeakerDiarizationSessionTest(unittest.TestCase):
    def test_meeting_stress_exports_the_final_diarization_timeline(self) -> None:
        carrier = DEVICE_STRESS.read_text(encoding="utf-8")
        self.assertIn("SpeakerDiarizationResult", carrier)
        self.assertIn("onSpeakerDiarizationUpdate(", carrier)
        self.assertIn("onSpeakerDiarizationResult(", carrier)
        self.assertIn("speakerDiarizationResults", carrier)
        self.assertIn("speakerTurnsHex", carrier)
        meeting_cycle = carrier.split("async function runCustomerScenarioCycle", 1)[1].split(
            "async function run", 1
        )[0]
        self.assertIn("events.speakerDiarizationTerminalResults === 1", meeting_cycle)
        self.assertIn("events.speakerDiarizationViolations === 0", meeting_cycle)
        self.assertIn("events.speakerDiarizationDegraded === 0", meeting_cycle)
        self.assertIn("events.speakerDiarizationSpeakerCount > 0", meeting_cycle)
        self.assertIn("events.speakerTurnsJson !== '[]'", meeting_cycle)
        self.assertIn("speakerDiarizationTerminalOrderOk", meeting_cycle)

    def test_public_diarization_api_is_generic_optional_and_does_not_reuse_asr_last_fields(self) -> None:
        models = PUBLIC_MODELS.read_text(encoding="utf-8")
        for field in ("utteranceId?", "speakerIndex: number = -1",
                      "secondarySpeakerIndexes: number[] = []",
                      "speakerConfidence: number = 0"):
            self.assertIn(field, models)
        self.assertIn("speakerDiarization?: SpeakerDiarizationConfig", models)
        self.assertIn("export class SpeakerDiarizationConfig", models)
        self.assertIn("maxSpeakers: number = 4", models)
        self.assertNotIn("serviceUrl", models)
        self.assertNotIn("serviceHeaders", models)
        self.assertIn("onSpeakerDiarizationUpdate?", models)
        self.assertIn("onSpeakerDiarizationResult?", models)
        self.assertIn("export class SpeakerDiarizationUpdate", models)
        self.assertIn("export class SpeakerDiarizationResult", models)
        self.assertIn("export enum SpeakerDiarizationDegradedReason", models)
        diarization_result = models.split(
            "export class SpeakerDiarizationResult", 1
        )[1].split("}", 1)[0]
        self.assertNotIn("isLast", diarization_result)
        self.assertNotIn("isFinal", diarization_result)

        adapter = ADAPTER.read_text(encoding="utf-8")
        for removed_name in (
            "enableSpeakerDiarization",
            "maxSpeakerCount",
            "expectedActiveSpeakerCount",
            "speakerCountHint",
            "speakerDiarizationProcessEntry",
            "onSpeakerUpdate",
            "SpeakerUpdate",
        ):
            self.assertNotIn(removed_name, models + adapter)
        self.assertIn("params.speakerDiarization", adapter)
        self.assertNotIn("resolveSpeakerDiarizationProcessEntry", adapter)
        for meeting_scoped_name in (
            "enableMeetingSpeakerSeparation",
            "maxMeetingSpeakers",
            "meetingSpeakerProcessEntry",
            "onMeetingResult",
            "MeetingResult",
        ):
            self.assertNotIn(meeting_scoped_name, models + adapter)

    def test_public_speaker_indexes_have_stable_defaults_and_config_is_validated(self) -> None:
        run_node(
            f"""
            import assert from 'node:assert/strict';
            import {{ validateSpeakerDiarizationConfig }} from {CONFIG_POLICY.as_uri()!r};

            assert.equal(validateSpeakerDiarizationConfig({{ maxSpeakers: 4 }}), 4);
            assert.equal(validateSpeakerDiarizationConfig({{ maxSpeakers: 2 }}), 2);
            for (const maxSpeakers of [0, 5, 1.5, Number.NaN, Number.POSITIVE_INFINITY]) {{
              assert.throws(() => validateSpeakerDiarizationConfig({{ maxSpeakers }}));
            }}
            """
        )

    def test_local_executor_is_sdk_owned_and_has_no_network_or_host_adapter(self) -> None:
        adapter = ADAPTER.read_text(encoding="utf-8")
        self.assertNotIn("childProcessManager", adapter)
        self.assertNotIn("resolveSpeakerDiarizationProcessEntry", adapter)
        self.assertIn("validateSpeakerDiarizationConfig", adapter)

        entry_ability = ENTRY_ABILITY.read_text(encoding="utf-8")
        self.assertNotIn("SpeakerDiarizationChild", entry_ability)

        client = LOCAL_CLIENT.read_text(encoding="utf-8")
        self.assertIn("CommunityDiarizationInference", client)
        self.assertIn("this.inference.load(context)", client)
        inference = (CORE_DIARIZATION.parent / "CommunityDiarizationInference.ets").read_text()
        self.assertIn("context.resourceManager", inference)
        self.assertIn("loadCommunityDiarizationResources(context.resourceManager)", inference)
        self.assertNotIn("NetworkKit", client)
        self.assertNotIn("http.createHttp", client)
        self.assertNotIn("startArkChildProcess", client)

        manifest = DEMO_MANIFEST.read_text(encoding="utf-8")
        self.assertNotIn("ohos.permission.INTERNET", manifest)
        self.assertFalse((DIARIZATION / "SpeakerDiarizationRemoteClient.ets").exists())
        self.assertFalse((ROOT / "delivery/harmony-dingqiao/delivery/run_speaker_diarization_service.py").exists())

    def test_local_model_load_and_inference_are_quiescent_before_runtime_release(self) -> None:
        client = LOCAL_CLIENT.read_text(encoding="utf-8")
        inference = CORE_DIARIZATION.read_text(encoding="utf-8")
        self.assertIn("private loadSettled: boolean = false", client)
        self.assertIn("!this.loadSettled", client)
        self.assertIn("await this.settleInference(inferencePromise)", client)
        self.assertIn("AmphionRuntime.getOrCreateSpeakerTurnSegmenterAsync", inference)
        self.assertNotIn("unloadSpeakerTurnSegmentationModel", inference)

    def test_internal_speaker_ids_map_to_absolute_zero_based_public_indexes(self) -> None:
        run_node(
            f"""
            import assert from 'node:assert/strict';
            import {{
              UNASSIGNED_SPEAKER_INDEX,
              speakerIndexFromInternalId,
              speakerIndexesFromInternalIds
            }} from {SPEAKER_INDEX_POLICY.as_uri()!r};

            assert.equal(UNASSIGNED_SPEAKER_INDEX, -1);
            assert.equal(speakerIndexFromInternalId('UNKNOWN'), -1);
            assert.equal(speakerIndexFromInternalId('S1'), 0);
            assert.equal(speakerIndexFromInternalId('S2'), 1);
            assert.equal(speakerIndexFromInternalId('S4'), 3);
            assert.equal(speakerIndexFromInternalId('S5'), -1);
            assert.equal(speakerIndexFromInternalId('S3', 2), -1);
            assert.equal(speakerIndexFromInternalId('S0'), -1);
            assert.equal(speakerIndexFromInternalId('speaker-1'), -1);
            assert.deepEqual(
              speakerIndexesFromInternalIds(['S2', 'UNKNOWN', 'S1', 'S2']),
              [1, 0]
            );
            assert.deepEqual(
              speakerIndexesFromInternalIds(['S2', 'UNKNOWN_SECONDARY'], 4, true),
              [1, -1]
            );
            """
        )

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

        session = SESSION.read_text(encoding="utf-8")
        self.assertIn("communityTimeline(clustered.turns, identity.mapping", session)
        self.assertIn("assignment.secondarySpeakerIds, this.maxSpeakers, true", session)

    def test_rejected_speaker_vad_final_redacts_raw_and_processed_text(self) -> None:
        runtime = RUNTIME.read_text(encoding="utf-8")
        rejection = runtime.split("if (speakerVadReject) {", 1)[1].split(
            "if (this.targetSpeakerEnabled)", 1
        )[0]
        self.assertIn("result.rawText = '';", rejection)
        self.assertIn("result.text = '';", rejection)

    def test_all_asr_last_paths_join_the_diarization_finish_barrier(self) -> None:
        adapter = ADAPTER.read_text(encoding="utf-8")
        rejected = adapter.split("handleFinalRejected", 1)[1].split(
            "handleAsrError", 1
        )[0]
        fallback = adapter.split("handleSessionStopped", 1)[1].split(
            "private ensureAlive", 1
        )[0]
        self.assertIn(
            "diarization.observeAsrFinal(payload, result)", rejected
        )
        self.assertGreater(rejected.index("diarization.asrFinalDelivered(result)"),
                           rejected.index("this.listener?.onResult?.(sessionId, payload)"))
        self.assertIn(
            "speakerDiarizationFinishBarrier?.resolveAsr(payload)", rejected
        )
        self.assertIn(
            "speakerDiarizationSession.observeAsrFinal(result, asrTail)", fallback
        )
        self.assertIn(
            "speakerDiarizationFinishBarrier?.resolveAsr(result)", fallback
        )

    def test_diarization_initialization_failure_degrades_without_failing_asr_start(self) -> None:
        adapter = ADAPTER.read_text(encoding="utf-8")
        diarization_start = adapter.split(
            "params.speakerDiarization", 1
        )[1].split("publishSession", 1)[0]
        self.assertIn("try {", diarization_start)
        self.assertIn("new DegradedSpeakerDiarizationSession", diarization_start)
        self.assertIn("SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE", diarization_start)

        process_client = LOCAL_CLIENT.read_text(encoding="utf-8")
        self.assertIn(
            "onDegraded(reason: SpeakerDiarizationDegradedReason, message: string)",
            process_client,
        )
        self.assertIn("SpeakerDiarizationDegradedReason.INFERENCE_UNAVAILABLE", process_client)
        self.assertIn("SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE", process_client)
        self.assertIn("SpeakerDiarizationDegradedReason.MODEL_UNAVAILABLE", process_client)
        session = SESSION.read_text(encoding="utf-8")
        self.assertNotIn("function degradedReasonOf", session)
        self.assertIn("speaker diarization initialization failed", diarization_start)

    def test_local_executor_preserves_padded_window_offset(self) -> None:
        client = LOCAL_CLIENT.read_text(encoding="utf-8")
        method = client[client.index("  private readWindow("):client.index("  private fail(")]
        method = method.replace("private ", "").replace(": DiarizationLocalJob", "").replace(": Float32Array", "").replace(": ArrayBuffer", "")
        run_node("class Reader {\n" + method + "}\n" + """
          import assert from 'node:assert/strict';
          const WINDOW_SAMPLES=160000;
          const samples=new Int16Array([-32768,16384,0,32767]);
          const r=new Reader();let observed;
          r.spool={read(offset,bytes){observed=[offset,bytes];return samples.buffer;}};
          const pcm=r.readWindow({offsetBytes:32000,sampleCount:4});
          assert.deepEqual(observed,[32000,8]);
          assert.equal(pcm.length,160000);
          assert.deepEqual(Array.from(pcm.slice(0,4)),[-1,.5,0,32767/32768]);
          assert.ok(pcm.slice(4).every(v=>v===0),'right padding cannot move real PCM');
        """)

    def test_spool_failure_is_isolated_from_asr_and_finish(self) -> None:
        client = LOCAL_CLIENT.read_text(encoding="utf-8")
        append_body = client.split("append(audio: ArrayBuffer)", 1)[1].split(
            "finish(): void", 1
        )[0]
        finish_body = client.split("finish(): void", 1)[1].split("cancel(): void", 1)[0]
        self.assertIn(
            "this.fail(SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE",
            append_body,
        )
        self.assertIn("speaker diarization spool failed:", append_body)
        self.assertIn(
            "this.fail(SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE",
            finish_body,
        )
        self.assertIn("speaker diarization finish spool failed:", finish_body)
        self.assertIn("Promise.race([inferencePromise, timeoutPromise])", client)
        self.assertIn("await this.settleInference(inferencePromise)", client)
        self.assertIn("this.closeWhenQuiescent()", client)
        self.assertIn("client.cleanup((): void => { this.releaseRuntimeLease(); })",
                      SESSION.read_text(encoding="utf-8"))

    def test_local_result_storage_failures_are_classified_as_storage_failures(self) -> None:
        client = LOCAL_CLIENT.read_text(encoding="utf-8")
        self.assertIn("SpeakerDiarizationStorageError", client)
        self.assertIn("error instanceof SpeakerDiarizationStorageError", client)
        self.assertIn("SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE", client)

        session = SESSION.read_text(encoding="utf-8")
        self.assertNotIn("appendCheckpoint", session)
        self.assertIn("this.spool.read", client)

    def test_caller_session_id_never_participates_in_job_paths(self) -> None:
        client = LOCAL_CLIENT.read_text(encoding="utf-8")
        constructor = client.split("constructor(context:", 1)[1].split(
            "append(audio:", 1
        )[0]
        self.assertIn("/speaker-diarization-jobs/job-${Date.now()}-${localJobId}", constructor)
        self.assertNotIn("/speaker-diarization-jobs/${sessionId}", constructor)

    def test_segments_crossing_a_stable_boundary_are_clipped_not_dropped(self) -> None:
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ communityTimeline }} from {(DIARIZATION/'CommunitySpeakerIdentity.ts').as_uri()!r};
          const tracks=[[100,1500,0],[900,1100,1]];
          const first=communityTimeline(tracks,[0,1],0,1000);
          const next=communityTimeline(tracks,[0,1],1000,2000);
          assert.deepEqual(first.map(t=>[t.beginTime,t.endTime,t.speakerId,t.secondarySpeakerIds]),
            [[100,900,'S1',[]],[900,1000,'S1',['S2']]]);
          assert.deepEqual(next.map(t=>[t.beginTime,t.endTime,t.speakerId,t.secondarySpeakerIds]),
            [[1000,1100,'S1',['S2']],[1100,1500,'S1',[]]]);
        """)

    def test_window_schedule_is_frame_independent_and_finish_flushes_tail(self) -> None:
        run_node(
            f"""
            import assert from 'node:assert/strict';
            import {{ DiarizationWindowScheduler }} from {SCHEDULER.as_uri()!r};

            const whole = new DiarizationWindowScheduler(16_000);
            const framed = new DiarizationWindowScheduler(16_000);
            const wholeWindows = whole.acceptSamples(16_000 * 17);
            const framedWindows = [];
            for (let i = 0; i < 17 * 50; i++) {{
              framedWindows.push(...framed.acceptSamples(320));
            }}
            assert.deepEqual(framedWindows, wholeWindows);
            assert.deepEqual(wholeWindows.map(window => [window.startSample, window.endSample]),
              Array.from({{length:8}},(_,i)=>[i*16000,(i+10)*16000]));
            assert.equal(whole.finish(),undefined,'an exact complete window must not be duplicated');
            framed.acceptSamples(320);
            const tail=framed.finish();
            assert.equal(tail.startSample,128000);
            assert.equal(tail.endSample,288000);
            assert.equal(tail.realEndSample,272320);
            assert.equal(tail.stableEndSample,272320);
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
            import {{ SpeakerDiarizationGlobalClusterer }} from {CLUSTERER.as_uri()!r};

            const clusterer = new SpeakerDiarizationGlobalClusterer(4, 2);
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

            const longSession = [];
            for (let i = 0; i < 3000; i++) {{
              longSession.push({{
                embedding: i % 2 === 0 ? [1, 0] : [0, 1],
                durationMs: 2000,
                onlineSpeakerId: i % 2 === 0 ? 'S1' : 'S2'
              }});
            }}
            assert.equal(clusterer.cluster(longSession).clusterCount, 2);
            """
        )

    def test_finish_barrier_orders_final_callbacks_and_degrades_on_timeout(self) -> None:
        run_node(
            f"""
            import assert from 'node:assert/strict';
            import {{ SpeakerDiarizationFinishBarrier }} from {BARRIER.as_uri()!r};

            const events = [];
            const barrier = new SpeakerDiarizationFinishBarrier(100, result => events.push(result));
            barrier.begin();
            barrier.resolveSpeaker({{ degraded: false, value: 'diarization-final' }});
            assert.deepEqual(events, []);
            barrier.resolveAsr('asr-last');
            assert.deepEqual(events,
              [{{ asr: 'asr-last', speaker: 'diarization-final', degraded: false }}]);
            barrier.resolveAsr('duplicate');
            assert.equal(events.length, 1);

            const timedOut = [];
            const timeoutBarrier = new SpeakerDiarizationFinishBarrier(20, result => timedOut.push(result));
            timeoutBarrier.begin();
            timeoutBarrier.resolveAsr('tail');
            await new Promise(resolve => setTimeout(resolve, 40));
            assert.deepEqual(timedOut, [{{ asr: 'tail', speaker: undefined, degraded: true }}]);
            timeoutBarrier.resolveSpeaker({{ degraded: false, value: 'late' }});
            assert.equal(timedOut.length, 1);

            const missingAsr = [];
            const missingAsrBarrier = new SpeakerDiarizationFinishBarrier(
              20, result => missingAsr.push(result));
            missingAsrBarrier.begin();
            await new Promise(resolve => setTimeout(resolve, 40));
            assert.deepEqual(missingAsr, []);
            missingAsrBarrier.resolveAsr('actual-tail');
            missingAsrBarrier.resolveSpeaker({{ degraded: false, value: 'speakers' }});
            assert.deepEqual(missingAsr, [{{
              asr: 'actual-tail', speaker: 'speakers', degraded: false
            }}]);
            """
        )

    def test_stopped_fallback_preserves_real_tail_waiting_for_speaker_decoration(self) -> None:
        from asr.tools.tests.test_harmony_speaker_inference_threading import method_body

        stopped = method_body(ADAPTER.read_text(), "handleSessionStopped").replace("(): void =>", "() =>")
        run_node(
            f"""
            import assert from 'node:assert/strict';
            import {{ SpeakerDiarizationFinishBarrier }} from {BARRIER.as_uri()!r};
            const STOP_FALLBACK_DELAY_MS = 1500;
            let timers = [];
            globalThis.setTimeout = (fn,ms) => {{ timers.push({{fn,ms}}); return timers.length; }};
            globalThis.clearTimeout = () => {{}};
            class SpeechRecognitionResult {{ result=''; isFinal=false; isLast=false; speakerIndex=-1; }}
            class AsrResult {{ isLast=false; }}
            class Engine {{
              generation=1; busy=true; finishRequested=true; completeSent=false;
              currentSessionId='s1'; finalResultSent=true; targetSpeakerEnhancementEnabled=false;
              sessionStartGate={{isCurrent: generation => generation===this.generation}};
              speakerDiarizationSession; speakerDiarizationFinishBarrier;
              listener={{onResult: (_id,value) => this.published.push(value)}};
              observed=[]; published=[]; tail;
              diagnosticResult() {{}}
              completeCurrentSession() {{ this.completeSent=true; }}
              tearDownSession() {{ this.busy=false; }}
              handleSessionStopped(generation) {{ {stopped} }}
            }}
            for (const arrival of ['before-stop','before-fallback','missing','cancelled']) {{
              timers=[];
              const engine=new Engine();
              const barrier=new SpeakerDiarizationFinishBarrier(15000, result => {{
                engine.published.push(result.asr); engine.completeCurrentSession();
              }});
              engine.speakerDiarizationFinishBarrier=barrier;
              engine.speakerDiarizationSession={{observeAsrFinal: value => {{
                engine.observed.push(value); engine.tail=value;
              }}}};
              barrier.begin();
              const real=new SpeechRecognitionResult(); real.result='真实尾句'; real.isLast=true;
              const arrive=() => {{ engine.speakerDiarizationSession.observeAsrFinal(real);
                barrier.resolveAsr(real); }};
              if (arrival==='before-stop') arrive();
              engine.handleSessionStopped(1);
              if (arrival==='before-fallback') arrive();
              if (arrival==='cancelled') {{ engine.generation=2; engine.currentSessionId='s2'; }}
              timers.find(timer => timer.ms===1500).fn();
              if (arrival==='cancelled') {{
                assert.deepEqual(engine.observed,[]); assert.deepEqual(engine.published,[]); continue;
              }}
              assert.equal(engine.observed.length,1,'fallback replaced an already available ASR tail');
              if (arrival!=='missing') assert.equal(engine.tail,real);
              else assert.equal(engine.tail.result,'','missing ASR tail still needs the stopped fallback');
              engine.tail.speakerIndex=2;
              assert.deepEqual(engine.published,[],'speaker work still pending');
              barrier.resolveSpeaker({{degraded:false,value:'final-speakers'}});
              assert.equal(engine.published.length,1);
              assert.equal(engine.published[0].speakerIndex,2,'decoration applied to the wrong tail');
              assert.equal(engine.published[0].result,arrival==='missing'?'':'真实尾句');
              assert.equal(engine.completeSent,true);
            }}
            timers=[];
            const plain=new Engine(); plain.handleSessionStopped(1); timers[0].fn();
            assert.equal(plain.published.length,1,'non-diarization stopped fallback changed');
            assert.equal(plain.published[0].isLast,true);
            assert.equal(plain.completeSent,true);
            """
        )

    def test_diarization_timeout_never_replaces_pending_asr_tail(self) -> None:
        run_node(
            f"""
            import assert from 'node:assert/strict';
            import {{ SpeakerDiarizationFinishBarrier }} from {BARRIER.as_uri()!r};
            let expire;
            globalThis.setTimeout = fn => {{ expire = fn; return 1; }};
            globalThis.clearTimeout = () => {{}};
            for (const speakerFirst of [false, true]) {{
              expire = undefined;
              const events = [];
              const barrier = new SpeakerDiarizationFinishBarrier(
                15000, result => events.push(result));
              barrier.begin();
              if (speakerFirst) barrier.resolveSpeaker({{ degraded: false, value: 'speakers' }});
              assert.equal(expire, undefined, 'ASR backlog is not a diarization timeout');
              assert.deepEqual(events, [], 'accepted PCM must drain before last/complete');
              barrier.resolveAsr('actual-tail-after-draining');
              if (!speakerFirst) {{
                assert.deepEqual(events, []);
                expire();
              }}
              assert.deepEqual(events, [{{
                asr: 'actual-tail-after-draining',
                speaker: speakerFirst ? 'speakers' : undefined,
                degraded: !speakerFirst,
              }}]);
              barrier.resolveAsr('duplicate');
              barrier.resolveSpeaker({{ degraded: false, value: 'late-speakers' }});
              expire?.();
              assert.equal(events.length, 1);
            }}
            """
        )
        self.assertNotIn("createSpeakerDiarizationTimeoutLastResult", ADAPTER.read_text())

    def test_diarization_runtime_release_waits_for_active_native_work(self) -> None:
        run_node(
            f"""
            import assert from 'node:assert/strict';
            import {{ SpeakerDiarizationRuntimeLeaseRegistry }} from {RUNTIME_LEASE.as_uri()!r};

            assert.equal(SpeakerDiarizationRuntimeLeaseRegistry.hasActiveLeases(), false);
            const lease = SpeakerDiarizationRuntimeLeaseRegistry.acquire();
            assert.equal(SpeakerDiarizationRuntimeLeaseRegistry.hasActiveLeases(), true);
            let released = false;
            const waiting = SpeakerDiarizationRuntimeLeaseRegistry.beginRelease().then(() => {{
              released = true;
              SpeakerDiarizationRuntimeLeaseRegistry.endRelease();
            }});
            await new Promise(resolve => setTimeout(resolve, 10));
            assert.equal(released, false);
            assert.throws(() => SpeakerDiarizationRuntimeLeaseRegistry.acquire());
            lease.release();
            await waiting;
            assert.equal(released, true);
            assert.equal(SpeakerDiarizationRuntimeLeaseRegistry.hasActiveLeases(), false);
            const next = SpeakerDiarizationRuntimeLeaseRegistry.acquire();
            next.release();
            """
        )

    def test_secondary_changes_do_not_fragment_primary_speech(self) -> None:
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState }} from {TIMELINE.as_uri()!r};
          const state=new SpeakerDiarizationTranscriptState();
          state.addUtterance({{rawText:'你叫什么名字',text:'你叫什么名字。',
            tokens:['你','叫','什','么','名','字'],tokenTimesMs:[100,300,500,700,900,1100],
            beginTime:0,endTime:1200}});
          const turns=[
            {{beginTime:0,endTime:250,speakerId:'S1',secondarySpeakerIds:[]}},
            {{beginTime:250,endTime:450,speakerId:'S1',secondarySpeakerIds:['UNKNOWN_SECONDARY'],overlap:true}},
            {{beginTime:450,endTime:650,speakerId:'S1',secondarySpeakerIds:['S2'],overlap:true}},
            {{beginTime:650,endTime:1200,speakerId:'S1',secondarySpeakerIds:[]}}
          ];
          state.applySpeakerTurns(turns);
          const before=state.allTurns();
          const result=state.finalUtterances();
          assert.deepEqual(result.map(x=>x.text),['你叫什么名字。'],
            'a secondary identity change must not split a word spoken by the same primary speaker');
          assert.equal(result[0].speakerId,'S1');
          assert.deepEqual(result[0].secondarySpeakerIds,['UNKNOWN_SECONDARY','S2']);
          assert.equal(result[0].overlap,true);
          assert.deepEqual(state.allTurns(),before,'exact overlap intervals must remain available');

          // Brief overlap between token timestamps must also survive paragraph grouping.
          const short=new SpeakerDiarizationTranscriptState();
          short.addUtterance({{rawText:'嗯好',text:'嗯，好。',tokens:['嗯','好'],
            tokenTimesMs:[100,700],beginTime:0,endTime:1000}});
          short.applySpeakerTurns([
            {{beginTime:0,endTime:250,speakerId:'S1',secondarySpeakerIds:[]}},
            {{beginTime:250,endTime:300,speakerId:'S1',secondarySpeakerIds:['S2'],overlap:true}},
            {{beginTime:300,endTime:600,speakerId:'S1',secondarySpeakerIds:[]}},
            {{beginTime:600,endTime:1000,speakerId:'S2',secondarySpeakerIds:[]}}
          ]);
          const split=short.commitThrough(1000);
          assert.deepEqual(split.map(x=>[x.text,x.speakerId]),[['嗯，','UNKNOWN'],['好。','S2']],
            'punctuation may expose the supported short answer but cannot resolve the overlapping clause');
          assert.deepEqual(split[0].secondarySpeakerIds,['S1','S2']);
          assert.equal(split[0].overlap,true);
          assert.deepEqual(short.finalUtterances(),[]);
        """)

    def test_bounded_unknown_backfill_preserves_real_changes_and_acoustic_evidence(self) -> None:
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState }} from {TIMELINE.as_uri()!r};
          const turn=(beginTime,endTime,speakerId,extra={{}})=>
            ({{beginTime,endTime,speakerId,secondarySpeakerIds:[],confidence:0.9,...extra}});
          function state(text,times,endTime,turns) {{
            const s=new SpeakerDiarizationTranscriptState();
            s.addUtterance({{rawText:text,text:text+'。',tokens:[...text],tokenTimesMs:times,
              beginTime:0,endTime}});
            s.applySpeakerTurns(turns); return s;
          }}
          const s=state('张三',[100,500],900,[turn(0,500,'S1'),turn(500,900,'UNKNOWN')]);
          const before=s.allTurns();
          const fixed=s.commitThrough(900);
          assert.deepEqual(fixed.map(x=>[x.text,x.speakerId]),[['张三。','S1']],
            'a short uncertain name ending should stay with its adjacent speaker');
          assert.equal(fixed[0].speakerInferred,true);
          assert.equal(fixed[0].confidence,0,'backfill must not inherit acoustic confidence');
          assert.equal(before[1].speakerId,'UNKNOWN');
          assert.deepEqual(s.finalUtterances(),[],'committed text must not be emitted again');
          for (const turns of [
            [turn(0,500,'UNKNOWN'),turn(500,900,'S1')],
            [turn(0,200,'S1'),turn(200,500,'UNKNOWN'),turn(500,900,'S1')]
          ]) {{
            const sample=state('你好啊',[100,300,600],900,turns);
            const original=sample.allTurns();
            assert.deepEqual(sample.finalUtterances().map(x=>x.speakerId),['S1']);
            assert.equal(sample.finalUtterances()[0].speakerInferred,true);
            assert.deepEqual(sample.allTurns(),original);
          }}
          for (const tail of [2500,2501]) {{
            const sample=state('甲乙',[100,500],500+tail,
              [turn(0,500,'S1'),turn(500,500+tail,'UNKNOWN')]);
            assert.deepEqual(sample.finalUtterances().map(x=>x.speakerId),
              tail===2500?['S1']:['S1','UNKNOWN'],'do not propagate identity through long unknown speech');
          }}
          const between=state('甲嗯乙',[100,500,900],1200,
            [turn(0,500,'S1'),turn(500,900,'UNKNOWN'),turn(900,1200,'S2')]);
          assert.deepEqual(between.finalUtterances().map(x=>x.speakerId),['S1','UNKNOWN','S2']);
          for (const extra of [{{overlap:true}},{{secondarySpeakerIds:['S2']}}]) {{
            const overlap=state('甲乙',[100,500],900,
              [turn(0,500,'S1'),turn(500,900,'UNKNOWN',extra)]);
            assert.deepEqual(overlap.finalUtterances().map(x=>x.speakerId),['S1','UNKNOWN']);
          }}
          const brief=state('甲乙',[100,500],900,[turn(0,500,'S1'),
            turn(500,600,'UNKNOWN'),turn(600,650,'S2'),turn(650,900,'UNKNOWN')]);
          assert.deepEqual(brief.finalUtterances().map(x=>x.speakerId),['S1','UNKNOWN'],
            'a real short turn between token timestamps blocks backfill');
          const alone=state('甲',[100],900,[turn(0,900,'UNKNOWN')]);
          alone.addUtterance({{rawText:'乙',text:'乙',tokens:['乙'],tokenTimesMs:[1000],
            beginTime:900,endTime:1200}});
          alone.applySpeakerTurns([turn(900,1200,'S1')]);
          assert.deepEqual(alone.finalUtterances().map(x=>x.speakerId),['UNKNOWN','S1']);
        """)

    def test_unknown_background_and_endpoint_tokens_do_not_split_words(self) -> None:
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState }} from {TIMELINE.as_uri()!r};
          const turn=(beginTime,endTime,speakerId,secondarySpeakerIds=[])=>
            ({{beginTime,endTime,speakerId,secondarySpeakerIds,overlap:secondarySpeakerIds.length>0}});
          function split(times,endTime,turns) {{
            const s=new SpeakerDiarizationTranscriptState();
            s.addUtterance({{rawText:'角色',text:'角色。',tokens:['角','色'],tokenTimesMs:times,
              beginTime:0,endTime}});
            s.applySpeakerTurns(turns);
            const before=s.allTurns(), result=s.finalUtterances();
            assert.deepEqual(s.allTurns(),before,'text inference must not rewrite acoustic evidence');
            return result;
          }}
          for (const turns of [
            [turn(0,400,'S1'),turn(400,700,'UNKNOWN')],
            [turn(0,400,'S1',['UNKNOWN_SECONDARY']),turn(400,700,'UNKNOWN')]
          ]) {{
            const result=split([100,500],500,turns);
            assert.deepEqual(result.map(x=>[x.text,x.speakerId]),[['角色。','S1']]);
            assert.equal(result[0].speakerInferred,true);
            assert.equal(result[0].confidence,0);
            assert.equal(result[0].overlap,turns[0].overlap);
          }}
          const head=split([100,500],800,[turn(0,150,'UNKNOWN'),
            turn(150,800,'S1',['UNKNOWN'])]);
          assert.deepEqual(head.map(x=>x.text),['角色。']);
          assert.equal(head[0].speakerInferred,true);
          assert.equal(head[0].overlap,true);
          assert.deepEqual(head[0].secondarySpeakerIds,['UNKNOWN']);
          for (const turns of [
            [turn(0,400,'S1',['S2']),turn(400,700,'UNKNOWN')],
            [turn(0,300,'S1'),turn(300,350,'S2'),turn(350,700,'UNKNOWN')],
            [turn(0,400,'S1'),turn(400,700,'S2')]
          ]) assert.equal(split([100,500],500,turns).length,2,
            'a real known speaker or overlap must still block inferred merging');
          assert.equal(split([100,3001],3001,[turn(0,400,'S1'),turn(400,3200,'UNKNOWN')]).length,2,
            'zero-duration endpoint must not bridge an arbitrarily long acoustic gap');
        """)

    def test_unanimous_speaker_and_bounded_backfill_keep_conflicting_or_overlapping_turns(self) -> None:
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState }} from {TIMELINE.as_uri()!r};
          function split(turns) {{
            const state=new SpeakerDiarizationTranscriptState();
            state.addUtterance({{rawText:'甲乙丙',text:'甲乙丙。',tokens:['甲','乙','丙'],
              tokenTimesMs:[100,600,1100],beginTime:0,endTime:1200}});
            state.applySpeakerTurns(turns);
            return state.finalUtterances();
          }}
          const first={{beginTime:0,endTime:500,speakerId:'S1',secondarySpeakerIds:[]}};
          const second={{beginTime:700,endTime:1000,speakerId:'S1',secondarySpeakerIds:[]}};
          assert.deepEqual(split([first,second]).map(x=>x.speakerId),['S1']);
          const unknown={{beginTime:500,endTime:1200,speakerId:'UNKNOWN',secondarySpeakerIds:[]}};
          assert.deepEqual(split([first,unknown]).map(x=>x.speakerId),['S1']);
          assert.deepEqual(split([first,{{...second,speakerId:'S2'}}]).map(x=>x.speakerId),
            ['S1','UNKNOWN']);
          // Overlap does not establish a unanimous single speaker for uncovered tokens.
          assert.deepEqual(split([{{...first,overlap:true,secondarySpeakerIds:['S2']}}])
            .map(x=>x.speakerId),['S1','UNKNOWN']);
          assert.deepEqual(split([]).map(x=>x.speakerId),['UNKNOWN']);
        """)

    def test_bbpe_alignment_keeps_multibyte_characters_whole(self) -> None:
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState }} from {TIMELINE.as_uri()!r};
          const state = new SpeakerDiarizationTranscriptState();
          state.addUtterance({{rawText:'你好啊',text:'你好，啊。',
            tokens:['▁Ƌ','ţŅƌŋţ','▁ƌĸī'],tokenTimesMs:[100,300,1200],beginTime:0,endTime:2000}});
          state.applySpeakerTurns([
            {{beginTime:0,endTime:200,speakerId:'S1',secondarySpeakerIds:[]}},
            {{beginTime:200,endTime:1000,speakerId:'S2',secondarySpeakerIds:[]}},
            {{beginTime:1000,endTime:2000,speakerId:'S3',secondarySpeakerIds:[]}}
          ]);
          const split=state.finalUtterances();
          assert.deepEqual(split.map(x=>x.rawText),['你','好','啊']);
          assert.deepEqual(split.map(x=>x.text),['你','好，','啊。']);
          assert.deepEqual(split.map(x=>x.speakerId),['S1','S2','S3']);
          // Native BBPE separators insert spaces after printable ASCII only.
          const english = new SpeakerDiarizationTranscriptState();
          english.addUtterance({{rawText:'HELLO WORLD',text:'HELLO, WORLD.',
            tokens:['▁HELLO','▁WORLD'],tokenTimesMs:[100,1100],beginTime:0,endTime:2000}});
          english.applySpeakerTurns([
            {{beginTime:0,endTime:1000,speakerId:'S1',secondarySpeakerIds:[]}},
            {{beginTime:1000,endTime:2000,speakerId:'S2',secondarySpeakerIds:[]}}
          ]);
          assert.equal(english.finalUtterances().map(x=>x.text).join(''),'HELLO, WORLD.');
          assert.deepEqual(english.finalUtterances().map(x=>x.speakerId),['S1','S2']);
        """)

    def test_punctuation_does_not_disable_timed_speaker_splitting(self) -> None:
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState }} from {TIMELINE.as_uri()!r};
          for (const text of ['甲乙丙丁', '甲乙，丙丁。', ' 甲乙！丙丁？']) {{
            const state = new SpeakerDiarizationTranscriptState();
            state.addUtterance({{rawText:'甲乙丙丁', text,
              tokens:['甲','乙','丙','丁'], tokenTimesMs:[100,500,1000,1500],
              beginTime:0, endTime:2000}});
            state.applySpeakerTurns([
              {{beginTime:0,endTime:900,speakerId:'S1',secondarySpeakerIds:[]}},
              {{beginTime:900,endTime:2000,speakerId:'UNKNOWN',secondarySpeakerIds:['S2'],overlap:true}}
            ]);
            const split = state.commitThrough(2000);
            assert.deepEqual(split.map(x => x.speakerId),
              text === '甲乙丙丁' ? ['UNKNOWN'] : ['UNKNOWN','UNKNOWN'], text);
            assert.equal(split.map(x => x.text).join(''), text);
            assert.equal(split.map(x => x.rawText).join(''), '甲乙丙丁');
            assert.deepEqual(split.map(x => [x.beginTime,x.endTime]),
              text === '甲乙丙丁' ? [[0,2000]] : [[0,1000],[1000,2000]]);
            assert.ok(split.every(x => x.sourceUtteranceId === 'u1' && x.overlap));
            assert.deepEqual(state.finalUtterances(), []);
            assert.deepEqual(split.map(x => x.text), text === '甲乙丙丁' ? [text] :
              text === '甲乙，丙丁。' ? ['甲乙，','丙丁。'] : [' 甲乙！','丙丁？']);
          }}
          // Lexical edits (ITN or rewritten words) have no safe character mapping.
          for (const text of ['23。', '甲戊，丙丁。']) {{
            const state = new SpeakerDiarizationTranscriptState();
            state.addUtterance({{rawText:'甲乙丙丁',text,tokens:['甲','乙','丙','丁'],
              tokenTimesMs:[100,500,1000,1500],beginTime:0,endTime:2000}});
            assert.deepEqual(state.finalUtterances().map(x => x.text), [text]);
          }}
        """)

    def test_transcript_revision_is_monotonic_and_token_split_conserves_text(self) -> None:
        run_node(
            f"""
            import assert from 'node:assert/strict';
            import {{ SpeakerDiarizationTranscriptState }} from {TIMELINE.as_uri()!r};

            const timeline = new SpeakerDiarizationTranscriptState();
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
              [['u1', 1, 'UNKNOWN']]);
            assert.deepEqual(timeline.applySpeakerTurns([]), []);
            const split = timeline.finalUtterances();
            assert.equal(split.map(item => item.text).join(''), '甲乙丙丁');
            assert.deepEqual(split.map(item => item.speakerId), ['S1', 'S2']);
            assert.deepEqual(split[1].secondarySpeakerIds, ['S1']);

            const fallback = new SpeakerDiarizationTranscriptState();
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

            const recent = new SpeakerDiarizationTranscriptState();
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

            const evidence = new SpeakerDiarizationTranscriptState();
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
