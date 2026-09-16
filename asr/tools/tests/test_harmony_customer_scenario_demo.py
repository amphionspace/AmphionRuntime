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
                  item.speakerDiarization && (item.speakerIndex >= 0 || item.speakerAssignmentFinal)
                    ? page.speakerLabel(item.displaySpeakerIndex) : '');
                return cache.get(key);
              }});
            }}
            assert.deepEqual(render(), ['说话人 1', '说话人 2', '']);
            const utterances = page.finalSegments.map((item, index) => ({{
              text: item.text, sourceUtteranceId: item.utteranceId,
              utteranceId: item.utteranceId + '-final', endTime: item.endTime,
              speakerIndex: index === 2 ? -1 : 0,
            }}));
            page.handleSpeakerDiarizationResult('live', {{
              windowIndex: 0, utterances, isSessionFinal: true, degraded: false,
            }});
            assert.deepEqual(page.finalSegments.map(item => item.speakerIndex), [0, 0, -1]);
            assert.deepEqual(render(), ['说话人 1', '说话人 1', '未能区分说话人'],
              'final callback must refresh labels even when the text does not change');
            // Late provisional updates cannot overwrite published assignments.
            page.handleSpeakerDiarizationUpdate('live', {{
              utteranceId: 'u2-final', revision: 99, speakerIndex: 1,
            }});
            assert.deepEqual(render(), ['说话人 1', '说话人 1', '未能区分说话人']);
            // A real second speaker must remain distinct.
            page.handleSpeakerDiarizationResult('live', {{
              windowIndex: 1, isSessionFinal: true, degraded: false,
              utterances: [{{sourceUtteranceId:'u4', utteranceId:'u4-final',
                text:'丁句', endTime:15000, speakerIndex:1}}],
            }});
            assert.equal(render().at(-1), '说话人 2');
        """
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / "speaker-display.mts"
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
        self.assertIn("return speakerIndex < 0 ? '未能区分说话人'", source)
        self.assertIn("item.speakerIndex >= 0 || item.speakerAssignmentFinal", source)
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
