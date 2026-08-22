import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SESSION = ROOT / "asr/android/sdk/src/main/java/com/amphion/asr/internal/SessionImpl.kt"
ENGINE_IMPL = ROOT / "asr/android/sdk/src/main/java/com/amphion/asr/internal/EngineImpl.kt"
RECOGNIZER = ROOT / (
    "asr/android/sdk/src/main/java/com/k2fsa/sherpa/onnx/OnlineRecognizer.kt"
)
DINGQIAO_ENGINE = ROOT / (
    "asr/android/sdk-dingqiao/src/main/java/com/amphion/dingqiao/"
    "DingqiaoRecognitionEngine.kt"
)
JNI_PATCH = ROOT / (
    "third_party/patches/sherpa-amphion/"
    "0020-feat-android-expose-rule3-checkpoint.patch"
)


class AndroidRule3EndpointTransitionTest(unittest.TestCase):
    def test_android_jni_exposes_endpoint_reason_and_checkpoint(self) -> None:
        wrapper = RECOGNIZER.read_text(encoding="utf-8")
        patch = JNI_PATCH.read_text(encoding="utf-8")

        self.assertIn("enum class OnlineEndpointReason", wrapper)
        self.assertIn("fun getEndpointReason(stream: OnlineStream)", wrapper)
        self.assertIn("fun commitRule3Segment(stream: OnlineStream)", wrapper)
        self.assertIn("OnlineRecognizer_getEndpointReason", patch)
        self.assertIn("OnlineRecognizer_commitRule3Segment", patch)
        self.assertIn("recognizer->GetEndpointReason(stream)", patch)
        self.assertIn("recognizer->CommitRule3Segment(stream)", patch)

    def test_session_uses_native_reason_instead_of_pcm_duration_guess(self) -> None:
        session = SESSION.read_text(encoding="utf-8")

        self.assertIn("recognizer.getEndpointReason(stream)", session)
        self.assertIn("transitionAfterNativeEndpoint(endpointReason, hasEvidence, isFinal)", session)
        self.assertIn("recognizer.commitRule3Segment(stream)", session)
        self.assertIn('"hard-restart"', session)
        self.assertIn('"soft-reset-fallback"', session)
        self.assertIn("evidence=$hasEvidence", session)
        self.assertNotIn("nativeStreamSamplesAccepted", session)

    def test_endpoint_reconfiguration_creates_before_closing_previous_engine(self) -> None:
        source = DINGQIAO_ENGINE.read_text(encoding="utf-8")
        method = source[source.index("private fun ensureRecognizerConfig") :]

        self.assertLess(method.index("buildEngine(startParams)"), method.index("previous?.close()"))

    def test_recognizer_pool_compares_endpoint_rules(self) -> None:
        source = ENGINE_IMPL.read_text(encoding="utf-8")

        self.assertIn("if (pool.endpointRules != other.endpointRules) return false", source)


if __name__ == "__main__":
    unittest.main()
