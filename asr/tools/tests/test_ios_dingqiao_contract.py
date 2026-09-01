import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
IOS = ROOT / "asr" / "ios" / "Sources" / "AmphionRuntime"
IOS_SAMPLE = ROOT / "asr" / "ios" / "Sample" / "ContentView.swift"
CONTRACT = ROOT / "shared" / "api-spec" / "dingqiao-asr-parameters.json"


class IosDingqiaoContractTest(unittest.TestCase):
    def test_public_parameter_names_are_present_in_ios_policy(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (IOS / "Dingqiao").glob("*.swift")
        )
        common_names = set(contract["create_engine"]["extra_params"])
        common_names.update(contract["start"]["extra_params"])
        for name in sorted(common_names):
            self.assertIn(f'"{name}"', source, name)

    def test_result_boundary_is_native_data_not_finish_inference(self):
        result = (IOS / "AsrResult.swift").read_text(encoding="utf-8")
        session = (IOS / "Internal" / "SessionCore.swift").read_text(encoding="utf-8")
        adapter = (IOS / "Dingqiao" / "DingqiaoRecognitionEngine.swift").read_text(encoding="utf-8")
        self.assertIn("public let isLast: Bool", result)
        self.assertIn("isLast: false", session)
        self.assertIn("isLast: true", session)
        self.assertIn("isLast: result.isLast", adapter)
        self.assertNotIn("finishRequested", adapter)

    def test_advanced_capabilities_require_real_models_and_voiceprint_ids(self):
        policy = (IOS / "Dingqiao" / "DingqiaoParameterPolicy.swift").read_text(encoding="utf-8")
        engine = (IOS / "Dingqiao" / "DingqiaoRecognitionEngine.swift").read_text(encoding="utf-8")
        voiceprint = (IOS / "Dingqiao" / "VoiceprintRuntime.swift").read_text(encoding="utf-8")
        diarization = (IOS / "Dingqiao" / "SpeakerDiarizationRuntime.swift").read_text(encoding="utf-8")
        for capability in (
            "enableVoiceprintVerification",
            "enableSpeakerVad",
            "speakerDiarization",
        ):
            self.assertIn(capability, policy)
        self.assertIn("voiceprint model is unavailable", engine)
        self.assertIn("voiceprintIds must contain at least one registered ID", engine)
        self.assertIn("speaker diarization models are unavailable", engine)
        self.assertIn("eres2net.onnx", voiceprint)
        self.assertIn("pyannote-segmentation-3.0.onnx", diarization)

    def test_capability_failures_precede_native_session_allocation(self):
        engine = (IOS / "Dingqiao" / "DingqiaoRecognitionEngine.swift").read_text(
            encoding="utf-8"
        )
        allocation = engine.index("let sessionEngine = try AsrEngine")
        self.assertLess(engine.index("voiceprint model is unavailable"), allocation)
        self.assertLess(engine.index("voiceprintIds must contain at least one registered ID"), allocation)
        self.assertLess(engine.index("speaker diarization models are unavailable"), allocation)

    def test_release_waits_for_active_streams(self):
        engine = (IOS / "Internal" / "EngineCore.swift").read_text(encoding="utf-8")
        session = (IOS / "Internal" / "SessionCore.swift").read_text(encoding="utf-8")
        self.assertIn("closeAndWait", engine)
        self.assertIn("decoderQueue.sync", session)
        self.assertLess(
            engine.index("closeAndWait"),
            engine.index("SherpaOnnxDestroyOnlineRecognizer(native)"),
        )

    def test_ios_passes_shared_bbpe_hotword_configuration(self):
        engine = (IOS / "Internal" / "EngineCore.swift").read_text(encoding="utf-8")
        layout = (IOS / "Internal" / "ModelLayout.swift").read_text(encoding="utf-8")
        config = (IOS / "AsrConfig.swift").read_text(encoding="utf-8")
        self.assertIn('"bbpe.vocab"', layout)
        self.assertIn('"bbpe"', engine)
        self.assertIn("bpeVocab:", engine)
        self.assertIn("c.maxActivePaths = 8", config)

    def test_demo_defaults_to_manual_ptt_without_initial_silence_timeout(self):
        sample = IOS_SAMPLE.read_text(encoding="utf-8")
        self.assertIn("@Published var scenario: DemoScenario = .pushToTalk", sample)
        self.assertIn('if scenario == .tapVad { values["vadBegin"] = 5_000 }', sample)


if __name__ == "__main__":
    unittest.main()
