from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
DEMO = ROOT / "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main"
PROFILE = DEMO / "ets/util/CustomerScenarioProfile.ets"
CASE_STORE = DEMO / "ets/util/DemoCaseStore.ets"
RECORDER = DEMO / "ets/util/AudioRecorder.ets"
WORKER = DEMO / "ets/workers/AudioCaptureWorker.ets"
CARRIER = DEMO / "ets/util/DeviceStressTest.ets"
INDEX = DEMO / "ets/pages/Index.ets"
DRIVER = ROOT / "delivery/harmony-dingqiao/delivery/run_device_stress.py"


class HarmonyCustomerScenarioDemoTest(unittest.TestCase):
    def test_customer_profiles_pin_the_mail_parameters(self) -> None:
        source = PROFILE.read_text(encoding="utf-8")

        self.assertIn("CUSTOMER_TAP_VAD", source)
        self.assertIn("vadBegin: 5000", source)
        self.assertIn("maxAudioDuration: 20000", source)
        self.assertIn("CUSTOMER_PTT", source)
        self.assertIn("maxAudioDuration: 62000", source)
        self.assertIn("CUSTOMER_TRANSCRIPTION", source)
        self.assertIn("vadEnd: 1600", source)
        self.assertIn("enablePartialResult: true", source)

    def test_audio_capture_source_is_forwarded_to_the_worker(self) -> None:
        recorder = RECORDER.read_text(encoding="utf-8")
        worker = WORKER.read_text(encoding="utf-8")

        self.assertIn("export type DemoAudioSource", recorder)
        self.assertIn("source: this.audioSource", recorder)
        self.assertIn("event.data['source']", worker)
        self.assertIn("SOURCE_TYPE_VOICE_RECOGNITION", worker)
        self.assertIn("SOURCE_TYPE_VOICE_COMMUNICATION", worker)

    def test_customer_stress_modes_are_public_and_keep_session_contracts(self) -> None:
        carrier = CARRIER.read_text(encoding="utf-8")
        driver = DRIVER.read_text(encoding="utf-8")

        for mode in ("customer-tap-vad", "customer-ptt", "customer-transcription", "customer-ptt-tail"):
            self.assertIn(mode, carrier)
            self.assertIn(f'"{mode}"', driver)
        self.assertIn("customerProfileStartParams", carrier)
        self.assertIn("lastBeforeStop === 0", carrier)
        self.assertIn("events.lastFinals === 1", carrier)
        self.assertIn("events.completes === 1", carrier)

    def test_live_demo_selects_the_profile_for_capture_and_start_params(self) -> None:
        source = INDEX.read_text(encoding="utf-8")

        self.assertIn("CUSTOMER_SCENARIOS", source)
        self.assertIn("customerProfileStartParams(sessionId, this.capturedCustomerScenario)", source)
        self.assertIn("this.capturedCustomerScenario = this.customerScenario", source)
        self.assertIn("this.capturedAudioSource = this.audioSource", source)
        self.assertIn("this.capturedAudioSource", source)
        self.assertIn("meta['audioSource'] = this.audioSourceName(this.capturedAudioSource)", source)
        self.assertIn("this.listening && this.rotatingSession", source)

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
