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
PUBLIC_MODELS = ROOT / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/DingqiaoModels.ets"
CONFIG_POLICY = DIARIZATION / "SpeakerDiarizationConfigPolicy.ts"
SPEAKER_INDEX_POLICY = DIARIZATION / "SpeakerDiarizationSpeakerIndex.ts"
REMOTE_CLIENT = DIARIZATION / "SpeakerDiarizationRemoteClient.ets"
SESSION = DIARIZATION / "SpeakerDiarizationSession.ets"
ADAPTER = ROOT / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
DEVICE_STRESS = ROOT / (
    "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/util/DeviceStressTest.ets"
)
ENTRY_ABILITY = ROOT / (
    "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/entryability/EntryAbility.ets"
)
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
        self.assertIn("events.speakerDiarizationResults === 1", meeting_cycle)
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
        self.assertIn("serviceUrl: string = ''", models)
        self.assertIn("serviceHeaders: Record<string, string> = {}", models)
        self.assertIn("maxSpeakers: number = 4", models)
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

            const valid = validateSpeakerDiarizationConfig({{
              serviceUrl: 'https://diarization.example/v1/window',
              serviceHeaders: {{ Authorization: 'Bearer token' }},
              maxSpeakers: 4
            }});
            assert.equal(valid.maxSpeakers, 4);
            assert.equal(valid.serviceUrl, 'https://diarization.example/v1/window');
            assert.equal(valid.serviceHeaders.Authorization, 'Bearer token');
            assert.equal(validateSpeakerDiarizationConfig({{
              serviceUrl: 'http://127.0.0.1:18080/v1/window',
              serviceHeaders: {{}}, maxSpeakers: 2
            }}).maxSpeakers, 2);
            assert.throws(() => validateSpeakerDiarizationConfig({{
              serviceUrl: 'http://remote.example/v1/window', serviceHeaders: {{}}, maxSpeakers: 4
            }}));
            assert.throws(() => validateSpeakerDiarizationConfig({{
              serviceUrl: '', serviceHeaders: {{}}, maxSpeakers: 4
            }}));
            assert.throws(() => validateSpeakerDiarizationConfig({{
              serviceUrl: 'https://diarization.example/v1/window',
              serviceHeaders: {{ Authorization: 'bad\\nvalue' }}, maxSpeakers: 4
            }}));
            assert.throws(() => validateSpeakerDiarizationConfig({{
              serviceUrl: 'https://diarization.example/v1/window', serviceHeaders: {{}}, maxSpeakers: 0
            }}));
            """
        )

    def test_remote_executor_replaces_host_child_process_adapter(self) -> None:
        adapter = ADAPTER.read_text(encoding="utf-8")
        self.assertNotIn("childProcessManager", adapter)
        self.assertNotIn("resolveSpeakerDiarizationProcessEntry", adapter)
        self.assertIn("diarizationConfig.serviceUrl", adapter)
        self.assertIn("diarizationConfig.serviceHeaders", adapter)

        entry_ability = ENTRY_ABILITY.read_text(encoding="utf-8")
        self.assertNotIn("SpeakerDiarizationChild", entry_ability)

        client = REMOTE_CLIENT.read_text(encoding="utf-8")
        self.assertIn("http.createHttp()", client)
        self.assertIn("X-Amphion-Protocol-Version", client)
        self.assertNotIn("startArkChildProcess", client)

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
        self.assertIn("channelIds.get(localSpeaker) ?? 'UNKNOWN_SECONDARY'", session)
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
            "speakerDiarizationSession.observeAsrFinal(payload, result)", rejected
        )
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

        process_client = REMOTE_CLIENT.read_text(encoding="utf-8")
        self.assertIn(
            "onDegraded(reason: SpeakerDiarizationDegradedReason, message: string)",
            process_client,
        )
        self.assertIn("SpeakerDiarizationDegradedReason.SERVICE_UNAVAILABLE", process_client)
        self.assertIn("SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE", process_client)
        self.assertIn("SpeakerDiarizationDegradedReason.AUTHENTICATION_FAILED", process_client)
        self.assertIn("SpeakerDiarizationDegradedReason.INVALID_SERVICE_RESPONSE", process_client)
        session = SESSION.read_text(encoding="utf-8")
        self.assertNotIn("function degradedReasonOf", session)
        self.assertIn("speaker diarization initialization failed", diarization_start)

    def test_remote_request_preserves_padded_window_offset_in_protocol(self) -> None:
        client = REMOTE_CLIENT.read_text(encoding="utf-8")
        self.assertGreaterEqual(client.count("contentStartInWindowSample: number"), 2)
        self.assertIn("X-Amphion-Content-Start-Sample", client)
        self.assertIn("result.contentStartInWindowSample !== job.contentStartInWindowSample", client)

    def test_spool_failure_is_isolated_from_asr_and_finish(self) -> None:
        client = REMOTE_CLIENT.read_text(encoding="utf-8")
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
        self.assertIn("job.attempt < 1", client)
        self.assertIn("this.activeRequest?.destroy()", client)
        self.assertIn("client.cleanup((): void => { this.releaseRuntimeLease(); })",
                      SESSION.read_text(encoding="utf-8"))

    def test_parent_result_storage_failures_are_not_reported_as_service_failures(self) -> None:
        client = REMOTE_CLIENT.read_text(encoding="utf-8")
        self.assertIn("SpeakerDiarizationStorageError", client)
        self.assertIn("error instanceof SpeakerDiarizationStorageError", client)
        self.assertIn("SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE", client)

        session = SESSION.read_text(encoding="utf-8")
        self.assertIn("throw new SpeakerDiarizationStorageError", session)

    def test_caller_session_id_never_participates_in_job_paths(self) -> None:
        client = REMOTE_CLIENT.read_text(encoding="utf-8")
        constructor = client.split("constructor(workPath:", 1)[1].split(
            "append(audio:", 1
        )[0]
        self.assertIn("/speaker-diarization-jobs/job-${Date.now()}-${localJobId}", constructor)
        self.assertNotIn("/speaker-diarization-jobs/${sessionId}", constructor)

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
            import {{ DiarizationWindowScheduler }} from {SCHEDULER.as_uri()!r};

            const whole = new DiarizationWindowScheduler(16_000);
            const framed = new DiarizationWindowScheduler(16_000);
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
              20, result => missingAsr.push(result), () => 'timeout-last');
            missingAsrBarrier.begin();
            await new Promise(resolve => setTimeout(resolve, 40));
            assert.deepEqual(missingAsr, [{{
              asr: 'timeout-last', speaker: undefined, degraded: true
            }}]);
            """
        )

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
              [['u1', 1, 'S1']]);
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
