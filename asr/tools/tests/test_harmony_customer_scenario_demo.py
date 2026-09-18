from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[3]
DEMO = ROOT / "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main"
PROFILE = DEMO / "ets/util/CustomerScenarioProfile.ets"
CASE_STORE = DEMO / "ets/util/DemoCaseStore.ets"
RECORDER = DEMO / "ets/util/AudioRecorder.ets"
WORKER = DEMO / "ets/workers/AudioCaptureWorker.ets"
CARRIER = DEMO / "ets/util/DeviceStressTest.ets"
INDEX = DEMO / "ets/pages/Index.ets"
ENTRY_ABILITY = DEMO / "ets/entryability/EntryAbility.ets"
BACKGROUND_RECORDING = DEMO / "ets/util/BackgroundRecordingTask.ets"
MODULE = DEMO / "module.json5"
DRIVER = ROOT / "delivery/harmony-dingqiao/delivery/run_device_stress.py"
DISPLAY_INDEX = DEMO / "ets/util/SpeakerDisplayIndex.ts"
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


class HarmonyCustomerScenarioDemoTest(unittest.TestCase):
    def test_diarization_profile_shortens_pause_without_changing_other_limits(self) -> None:
        profile = PROFILE.read_text(encoding="utf-8").split("\n", 1)[1]
        script = f"""
            import assert from 'node:assert/strict';
            class StartParams {{ extraParams = {{}}; }}
            class AudioInfo {{}}
            class SpeakerDiarizationConfig {{}}
            {profile}
            for (const name of ['ptt','tap-vad','transcription','form','meeting-minutes']) {{
              const baseline = customerProfileStartParams('s',name,false);
              const enabled = customerProfileStartParams('s',name,true);
              assert.equal(enabled.extraParams.vadEnd,800);
              assert.equal(baseline.extraParams.vadEnd,customerScenarioProfile(name).vadEnd);
              for (const key of ['vadBegin','maxAudioDuration','endpointMaxUtteranceMs','recognizerMode']) {{
                assert.equal(enabled.extraParams[key],baseline.extraParams[key]);
              }}
              assert.equal(enabled.speakerDiarization.maxSpeakers,4);
            }}
            assert.equal(customerProfileStartParams('s','meeting-minutes').extraParams.vadEnd,800);
            assert.equal(customerProfileStartParams('s','ptt').extraParams.vadEnd,1600);
        """
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / "diarization-pause.mts"
            harness.write_text(textwrap.dedent(script), encoding="utf-8")
            subprocess.run(["node", "--experimental-strip-types", str(harness)], check=True, cwd=ROOT)

    def test_window_stress_budget_admits_five_hours_without_changing_customer_profiles(self) -> None:
        profile = PROFILE.read_text(encoding="utf-8").split("\n", 1)[1]
        carrier = CARRIER.read_text(encoding="utf-8")
        start = carrier.index("async function runCustomerScenarioCycle(")
        end = carrier.index("  engine.startListening(params);", start)
        setup = carrier[start:end] + "  engine.startListening(params);\n}\n"
        audio_limit = ROOT / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SessionAudioLimit.ts"
        script = f"""
            import assert from 'node:assert/strict';
            import {{ maxAudioBytesOf }} from '{audio_limit.as_uri()}';
            class StartParams {{ extraParams = {{}}; }}
            class AudioInfo {{}}
            class SpeakerDiarizationConfig {{}}
            class SessionEvents {{}}
            class StressListener {{}}
            {profile}
            {setup}
            const captured = [];
            const engine = {{ setListener() {{}}, startListening(params) {{ captured.push(params); }} }};
            for (const mode of ['diarization-windows', 'customer-meeting-minutes', 'customer-form']) {{
                await runCustomerScenarioCycle(engine, {{}}, 0, mode, 20);
            }}
            const [windows, meeting, form] = captured;
            for (const value of [400, 600, 800]) {{
                await runCustomerScenarioCycle(engine, {{}}, 0, 'diarization-windows', 20, value);
                assert.equal(captured.at(-1).extraParams.vadEnd, value);
            }}
            await runCustomerScenarioCycle(engine, {{}}, 0, 'customer-form', 20, 400);
            assert.equal(captured.at(-1).extraParams.vadEnd, form.extraParams.vadEnd);
            assert.equal(meeting.extraParams.vadEnd, 800);
            assert.ok(maxAudioBytesOf(windows.extraParams) > 18000000 * 32,
                'five-hour input must finish before the configured automatic stop');
            assert.equal(windows.extraParams.enableContinuousRecognition, false);
            assert.equal(windows.speakerDiarization.maxSpeakers, 4);
            assert.equal(meeting.extraParams.maxAudioDuration, 7200000);
            assert.equal(maxAudioBytesOf(meeting.extraParams), 7200000 * 32);
            assert.equal(form.extraParams.maxAudioDuration, 28800000);
        """
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / "carrier-params.mts"
            harness.write_text(textwrap.dedent(script), encoding="utf-8")
            subprocess.run([
                "node", "--experimental-strip-types", "--experimental-loader",
                TS_LOADER.as_uri(), str(harness),
            ], check=True, cwd=ROOT)

    def test_speaker_display_indexes_are_compact_and_keep_unassigned_hidden(self) -> None:
        run_node(
            f"""
            import assert from 'node:assert/strict';
            import {{ compactSpeakerDisplayIndexes }} from '{DISPLAY_INDEX.as_uri()}';

            assert.deepEqual(compactSpeakerDisplayIndexes([0, 3, 0, 3]), [0, 1, 0, 1]);
            assert.deepEqual(compactSpeakerDisplayIndexes([-1, 3, 1]), [-1, 0, 1]);
            assert.deepEqual(compactSpeakerDisplayIndexes([2, 2, 0]), [0, 0, 1]);
            """
        )

    def test_final_diarization_replaces_visible_roles_when_text_is_unchanged(self) -> None:
        source = INDEX.read_text(encoding="utf-8")
        segment = source.split("class FinalSegment {", 1)[1].split("\n@Entry", 1)[0]
        handlers = source.split("  handleSpeakerDiarizationUpdate(", 1)[1].split(
            "  private async finishAutoEndedCapture", 1
        )[0]
        display = source.split("  private speakerLabel(", 1)[1].split(
            "  private selectCustomerScenario", 1
        )[0]
        rows = source.split("ForEach(this.finalSegments,", 1)[1].split("\n      }", 1)[0]
        key = rows.rsplit("}, ", 1)[1].rstrip().removesuffix(")")
        label = rows.split("Span(", 1)[1].split("\n", 1)[0].rstrip().removesuffix(")")
        label = label.replace("this.segmentSpeakerLabel", "page.segmentSpeakerLabel")
        script = f"""
            import assert from 'node:assert/strict';
            class FinalSegment {{{segment}
            class Page {{
              replaySessionId = 'replay'; lastDiarizationWindowIndex = -1;
              capturedCustomerScenario = 'ptt'; finalSegments = [];
              handleSpeakerDiarizationUpdate({handlers}
              private speakerLabel({display}
            }}
            const keyOf = {key};
            const page = new Page();
            // Same-key ForEach rows retain their original non-observed item.
            page.finalSegments = [
              new FinalSegment('甲句', undefined, 'u1', 0, 4000, true),
              new FinalSegment('乙句', undefined, 'u2', 1, 9000, true),
              new FinalSegment('丙句', undefined, 'u3', -1, 12000, true),
            ];
            page.refreshSpeakerDisplayIndexes(page.finalSegments);
            const cache = new Map();
            function render() {{
              return page.finalSegments.map((item, index) => {{
                const key = keyOf(item, index);
                if (!cache.has(key)) cache.set(key,
                  item.speakerDiarization ? ({label}).trim() : '');
                return cache.get(key);
              }});
            }}
            assert.deepEqual(render(), ['说话人 1（中间结果）', '说话人 2（中间结果）',
              '不确定（中间结果）']);
            const utterances = page.finalSegments.map((item, index) => ({{
              text: item.text, sourceUtteranceId: item.utteranceId,
              utteranceId: item.utteranceId + '-final', endTime: item.endTime,
              speakerIndex: index === 2 ? -1 : 0, secondarySpeakerIndexes: [], overlap: false,
            }}));
            page.handleSpeakerDiarizationResult('live', {{
              windowIndex: 0, utterances, isSessionFinal: false, degraded: false,
            }});
            assert.deepEqual(page.finalSegments.map(item => item.speakerIndex), [0, 0, -1]);
            assert.deepEqual(render(), ['说话人 1（最终结果）', '说话人 1（最终结果）',
              '不确定（最终结果）'],
              'a committed window must refresh phase and identity before the session ends');
            // Late provisional updates cannot overwrite published assignments.
            page.handleSpeakerDiarizationUpdate('live', {{
              utteranceId: 'u2-final', revision: 99, speakerIndex: 1,
            }});
            assert.deepEqual(render(), ['说话人 1（最终结果）', '说话人 1（最终结果）',
              '不确定（最终结果）']);
            // A real second speaker must remain distinct.
            page.handleSpeakerDiarizationResult('live', {{
              windowIndex: 1, isSessionFinal: true, degraded: false,
              utterances: [{{sourceUtteranceId:'u4', utteranceId:'u4-final',
                text:'丁句', endTime:15000, speakerIndex:1, secondarySpeakerIndexes:[],
                overlap:false}}],
            }});
            assert.equal(render().at(-1), '说话人 2（最终结果）');
            const mixed = new Page();
            const parts = [
              {{sourceUtteranceId:'u1',utteranceId:'u1',text:'张',beginTime:0,endTime:200,
                speakerIndex:0,secondarySpeakerIndexes:[],overlap:false}},
              {{sourceUtteranceId:'u1',utteranceId:'u1.2',text:'三。',beginTime:200,endTime:400,
                speakerIndex:-1,secondarySpeakerIndexes:[1],overlap:true}},
              {{sourceUtteranceId:'u2',utteranceId:'u2',text:'你好。',beginTime:500,endTime:1000,
                speakerIndex:1,secondarySpeakerIndexes:[],overlap:false}},
            ];
            mixed.handleSpeakerDiarizationResult('live', {{
              windowIndex:0,utterances:parts,isSessionFinal:false,degraded:false,
            }});
            assert.deepEqual(mixed.finalSegments.map(x=>x.text),['张三。','你好。'],
              'one source sentence must stay readable despite uncertain role fragments');
            assert.deepEqual(mixed.finalSegments.map(x=>x.speakerIndex),[-1,1],
              'readability must not assign the uncertain character to its neighbour');
            assert.deepEqual(mixed.finalSegments[0].speakerParts,parts.slice(0,2),
              'exact known/unknown text, times and overlap remain inspectable');
            assert.equal(mixed.segmentSpeakerLabel(mixed.finalSegments[0]),
              '多人／不确定 · 含重叠发言');
            assert.equal(mixed.segmentSpeakerLabel(mixed.finalSegments[1]),'说话人 2');
            const multi = new FinalSegment('甲乙',undefined,'both',-1,1000,true,true);
            multi.speakerParts = [parts[0],parts[2]];
            assert.equal(mixed.segmentSpeakerLabel(multi),'多人／不确定',
              'do not relabel a multi-speaker paragraph using its majority speaker');
            const inferred = new FinalSegment('张三',undefined,'inferred',0,1000,true,true);
            inferred.speakerParts = [{{...parts[0],text:'张三',confidence:0,speakerInferred:true}}];
            assert.equal(mixed.segmentSpeakerLabel(inferred),'说话人 1 · 含推断补全',
              'bounded UNKNOWN backfill must be visible as an inference');
            mixed.handleSpeakerDiarizationUpdate('live',{{utteranceId:'u1',revision:99,speakerIndex:2}});
            assert.equal(mixed.finalSegments[0].speakerIndex,-1);
            mixed.handleSpeakerDiarizationResult('live', {{
              windowIndex:0,utterances:parts,isSessionFinal:false,degraded:false,
            }});
            assert.equal(mixed.finalSegments.length,2,'a repeated window must not duplicate paragraphs');
        """
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / "speaker-display.mts"
            harness.write_text(textwrap.dedent(script), encoding="utf-8")
            subprocess.run(["node", "--experimental-strip-types", str(harness)], check=True, cwd=ROOT)

    def test_demo_file_input_stops_at_eof_or_session_change(self) -> None:
        source = INDEX.read_text(encoding="utf-8")
        start = source.index("  private async feedDemoFile(")
        end = source.index("  // ---- Runtime", start)
        method = source[start:end]
        script = f"""
            import assert from 'node:assert/strict';
            const SDK_FRAME_BYTES = 640, FRAME_AUDIO_MS = 20;
            const bytes = Uint8Array.from({{length: 1920}}, (_, i) => i % 251);
            const WavIo = {{ readPcmBytes: () => bytes.buffer }};
            const timers = [];
            const setTimeout = (callback, delay) => {{
              assert.equal(delay, 20); timers.push(callback);
            }};
            class Page {{
              active = true; listening = true; stoppingListening = false;
              sessionId = 'a'; workPath = '/work'; frames = []; finishes = 0;
              feedFrameLive(frame) {{ this.frames.push(new Uint8Array(frame)); }}
              async stopListening() {{ this.finishes++; this.listening = false; }}
              handleStopFailure(sid, error) {{ throw error; }}
              {method}
            }}
            async function tick() {{ timers.shift()(); await Promise.resolve(); }}
            const complete = new Page();
            const done = complete.feedDemoFile('a');
            for (let i = 0; i < 3; i++) await tick();
            await done;
            assert.deepEqual(complete.frames.flatMap(frame => [...frame]), [...bytes]);
            assert.equal(complete.finishes, 1);
            for (const change of [
              page => page.stoppingListening = true,
              page => page.listening = false,
              page => page.active = false,
              page => page.sessionId = 'b',
            ]) {{
              const page = new Page();
              const run = page.feedDemoFile('a');
              change(page);
              await tick(); await run;
              assert.equal(page.frames.length, 1, 'no frame after stop or into another session');
              assert.equal(page.finishes, 0, 'old producer cannot finish another session');
            }}
            const lastFrame = new Page();
            const lastRun = lastFrame.feedDemoFile('a');
            await tick(); await tick();
            lastFrame.sessionId = 'b';
            await tick(); await lastRun;
            assert.equal(lastFrame.finishes, 0, 'EOF cannot finish a replacement session');
        """
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / "demo-file-input.mts"
            harness.write_text(textwrap.dedent(script), encoding="utf-8")
            subprocess.run(["node", "--experimental-strip-types", str(harness)], check=True, cwd=ROOT)

    def test_customer_profiles_pin_the_mail_parameters(self) -> None:
        source = PROFILE.read_text(encoding="utf-8")

        self.assertIn("CUSTOMER_TAP_VAD", source)
        self.assertIn("vadBegin: 5000", source)
        self.assertIn("maxAudioDuration: 20000", source)
        self.assertIn("endpointMaxUtteranceMs: 20000", source)
        self.assertIn("CUSTOMER_PTT", source)
        self.assertIn("maxAudioDuration: 62000", source)
        self.assertIn("CUSTOMER_TRANSCRIPTION", source)
        self.assertIn("vadEnd: 1600", source)
        self.assertGreaterEqual(source.count("endpointMaxUtteranceMs: 60000"), 3)
        self.assertIn("CUSTOMER_FORM", source)
        self.assertIn("maxAudioDuration: 28800000", source)
        self.assertIn("CUSTOMER_MEETING_MINUTES", source)
        self.assertIn("maxAudioDuration: 7200000", source)
        self.assertIn("speakerDiarizationMaxSpeakers: 4", source)
        self.assertGreaterEqual(source.count("vadEnd: 1500"), 2)
        self.assertGreaterEqual(source.count("allowVoiceprint: false"), 2)
        self.assertGreaterEqual(source.count("rotateSession: false"), 2)
        self.assertIn("export const SESSION_ROTATE_AUDIO_MS = 55000", source)
        self.assertIn("profile.maxAudioDuration > SESSION_ROTATE_AUDIO_MS", source)
        self.assertIn("enablePartialResult: true", source)
        self.assertIn("params.extraParams['endpointMaxUtteranceMs'] = profile.endpointMaxUtteranceMs", source)
        self.assertIn("params.speakerDiarization = diarization", source)
        self.assertIn("speakerDiarizationEnabled?: boolean", source)
        self.assertIn("profile.speakerDiarizationMaxSpeakers ?? 4", source)
        for removed_name in (
            "enableSpeakerDiarization",
            "maxSpeakerCount",
            "expectedActiveSpeakerCount",
            "speakerDiarizationProcessEntry",
        ):
            self.assertNotIn(removed_name, source)
        self.assertIn("params.extraParams['recognizerMode'] = profile.recognizerMode", source)
        self.assertGreaterEqual(source.count("recognizerMode: 'short'"), 2)
        self.assertGreaterEqual(source.count("recognizerMode: 'long'"), 3)
        self.assertEqual(source.count("\n  audioSource: 'mic',"), 5)

    def test_long_profiles_disable_rotation_and_periodic_rule3(self) -> None:
        profile = PROFILE.read_text(encoding="utf-8")
        index = INDEX.read_text(encoding="utf-8")

        self.assertIn("endpointMaxUtteranceMs: number", profile)
        self.assertIn("recognizerMode: 'short' | 'long'", profile)
        self.assertIn("recognizerMode: 'long'", profile)
        self.assertIn("customerProfileUsesContinuousRecognition(profile)", index)
        self.assertIn("extra['enableContinuousRecognition']", index)
        self.assertNotIn("this.rotateRecognitionSession", index)

    def test_audio_capture_source_is_forwarded_to_the_worker(self) -> None:
        recorder = RECORDER.read_text(encoding="utf-8")
        worker = WORKER.read_text(encoding="utf-8")

        self.assertIn("export type DemoAudioSource", recorder)
        self.assertIn("source: this.audioSource", recorder)
        self.assertIn("event.data['source']", worker)
        self.assertIn("SOURCE_TYPE_VOICE_RECOGNITION", worker)
        self.assertIn("SOURCE_TYPE_VOICE_COMMUNICATION", worker)

    def test_recording_sessions_own_an_audio_recording_continuous_task(self) -> None:
        index = INDEX.read_text(encoding="utf-8")
        entry = ENTRY_ABILITY.read_text(encoding="utf-8")
        background = BACKGROUND_RECORDING.read_text(encoding="utf-8")
        module = MODULE.read_text(encoding="utf-8")

        self.assertIn("ohos.permission.KEEP_BACKGROUND_RUNNING", module)
        self.assertIn('"backgroundModes": ["audioRecording"]', module)
        self.assertIn("BackgroundMode.AUDIO_RECORDING", background)
        self.assertIn("await BackgroundRecordingTask.start(ctx)", index)
        self.assertIn("BackgroundRecordingTask.stop(getContext(this)", index)
        self.assertIn("await BackgroundRecordingTask.start(this.context)", entry)
        self.assertIn("await BackgroundRecordingTask.stop(this.context)", entry)

    def test_customer_stress_modes_are_public_and_keep_session_contracts(self) -> None:
        carrier = CARRIER.read_text(encoding="utf-8")
        driver = DRIVER.read_text(encoding="utf-8")

        for mode in (
            "customer-tap-vad",
            "customer-ptt",
            "customer-transcription",
            "customer-ptt-tail",
            "customer-form",
            "customer-meeting-minutes",
        ):
            self.assertIn(mode, carrier)
            self.assertIn(f'"{mode}"', driver)
        self.assertIn("customerProfileStartParams", carrier)
        self.assertIn("params.extraParams['enableContinuousRecognition'] =", carrier)
        self.assertIn("customerProfileUsesContinuousRecognition(profile)", carrier)
        self.assertIn("lastBeforeStop === 0", carrier)
        self.assertIn("events.lastFinals === 1", carrier)
        self.assertIn("events.completes === 1", carrier)

    def test_live_demo_selects_the_profile_for_capture_and_start_params(self) -> None:
        source = INDEX.read_text(encoding="utf-8")

        self.assertIn("CUSTOMER_SCENARIOS", source)
        self.assertIn(
            "customerProfileStartParams(\n"
            "      sessionId, this.capturedCustomerScenario, this.capturedSpeakerDiarization)",
            source,
        )
        self.assertNotIn("speakerDiarizationServiceUrl", source)
        self.assertIn("this.capturedCustomerScenario = this.customerScenario", source)
        self.assertIn("this.capturedAudioSource = this.audioSource", source)
        self.assertIn("this.capturedAudioSource", source)
        self.assertIn("this.capturedSpeakerDiarization = this.speakerDiarizationDesired", source)
        self.assertIn("sessionId, this.capturedCustomerScenario, this.capturedSpeakerDiarization", source)
        self.assertIn("Text('角色分离')", source)
        self.assertIn("显示为“说话人 + 数字编号”", source)
        self.assertIn("`说话人 ${speakerIndex + 1}`", source)
        self.assertNotIn("return speakerIndex < 0 ? '说话人'", source)
        self.assertIn("return speakerIndex < 0 ? '不确定'", source)
        self.assertIn("if (item.speakerDiarization)", source)
        self.assertIn("item.speakerAssignmentFinal ? '最终结果' : '中间结果'", source)
        self.assertIn("next[i].endTime, true, next[i].speakerAssignmentFinal", source)
        self.assertIn("meta['audioSource'] = this.audioSourceName(this.capturedAudioSource)", source)
        self.assertIn("profile.allowVoiceprint", source)
        self.assertIn("customerProfileUsesContinuousRecognition(profile)", source)
        self.assertIn("profile.lockAudioSource", source)
        self.assertIn("@State audioSource: DemoAudioSource = 'mic'", source)
        self.assertIn("private capturedAudioSource: DemoAudioSource = 'mic'", source)
        self.assertIn("? '长语音' : '短语音'", source)
        self.assertIn("extra['enableContinuousRecognition']", source)
        self.assertIn("this.finishAutoEndedCapture().catch", source)
        self.assertIn("this.stopListening().catch", source)

    def test_demo_case_store_exports_audio_metadata_and_note_for_hdc(self) -> None:
        source = CASE_STORE.read_text(encoding="utf-8")
        index = INDEX.read_text(encoding="utf-8")

        self.assertIn("/data/storage/el2/base/files/asr-cases", source)
        self.assertIn("audio.wav", source)
        self.assertIn("metadata.json", source)
        self.assertIn("note.txt", source)
        self.assertIn("saveDemoCase", index)
        self.assertIn("caseNote", index)


if __name__ == "__main__":
    unittest.main()
