import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]
SOURCE = ROOT / "asr/harmony/sdk/src/main/cpp/target_speaker_enhancer.cpp"


class HarmonyTargetSpeakerNativeBoundaryTest(unittest.TestCase):
    def test_separator_session_is_shared_until_explicit_model_unload(self) -> None:
        text = SOURCE.read_text(encoding="utf-8")
        self.assertIn("std::shared_ptr<TargetSpeakerSeparator> g_separator_model", text)
        self.assertIn("LoadTargetSpeakerEnhancementModel", text)
        self.assertIn("IsTargetSpeakerEnhancementModelLoaded", text)
        self.assertIn("UnloadTargetSpeakerEnhancementModel", text)
        self.assertIn("std::shared_ptr<TargetSpeakerSeparator> separator", text)

    def test_typed_array_uses_view_byte_length_not_backing_buffer_size(self) -> None:
        text = SOURCE.read_text(encoding="utf-8")
        self.assertIn('napi_get_named_property(env, value, "byteLength"', text)
        self.assertIn("view_bytes / sizeof(T)", text)
        self.assertIn("length != element_count && length != view_bytes", text)
        self.assertIn("exceeds its backing buffer", text)


if __name__ == "__main__":
    unittest.main()
