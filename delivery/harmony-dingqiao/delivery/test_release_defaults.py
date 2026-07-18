from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]


class ReleaseDefaultsTest(unittest.TestCase):
    def test_speaker_vad_defaults_match_sdk_demo_and_public_docs(self) -> None:
        sdk = (
            REPO_ROOT
            / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/"
            "SpeechRecognizeSdk.ets"
        ).read_text(encoding="utf-8")
        demo = (
            REPO_ROOT
            / "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/pages/"
            "Index.ets"
        ).read_text(encoding="utf-8")
        docs = (
            REPO_ROOT / "delivery/harmony-dingqiao/docs/语音识别SDK接口.md"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "clamp(numberParam(extra, 'speakerVadThreshold', 0.35), -1.0, 1.0)",
            sdk,
        )
        self.assertIn(
            "clamp(numberParam(extra, 'speakerVadWindowMs', 1500), 500, 5000)",
            sdk,
        )
        self.assertIn(
            "clamp(numberParam(extra, 'speakerVadHopMs', 500), 100, 2000)",
            sdk,
        )
        self.assertIn("SPEAKER_VAD_THRESHOLD = 0.35", demo)
        self.assertIn("SPEAKER_VAD_WINDOW_MS = 1500", demo)
        self.assertIn("SPEAKER_VAD_HOP_MS = 500", demo)
        self.assertIn("| `speakerVadThreshold` | `number/string` | `0.35` |", docs)
        self.assertIn("| `speakerVadWindowMs` | `number/string` | `1500` |", docs)
        self.assertIn("| `speakerVadHopMs` | `number/string` | `500` |", docs)


if __name__ == "__main__":
    unittest.main()
