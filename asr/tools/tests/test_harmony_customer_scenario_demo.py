from pathlib import Path
import subprocess
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
