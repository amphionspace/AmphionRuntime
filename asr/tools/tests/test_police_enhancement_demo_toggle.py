import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
ANDROID_ENGINE = REPO_ROOT / (
    "asr/android/sdk-dingqiao/src/main/java/com/amphion/dingqiao/"
    "DingqiaoRecognitionEngine.kt"
)
ANDROID_DEMO = REPO_ROOT / (
    "asr/android/samples/dingqiao-demo/src/main/java/com/amphion/dingqiao/demo/"
    "MainActivity.kt"
)
ANDROID_PREFS = REPO_ROOT / (
    "asr/android/samples/dingqiao-demo/src/main/java/com/amphion/dingqiao/demo/"
    "DemoPrefs.kt"
)
ANDROID_LAYOUT = REPO_ROOT / (
    "asr/android/samples/dingqiao-demo/src/main/res/layout/activity_main.xml"
)
HARMONY_ENGINE = REPO_ROOT / (
    "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/"
    "SpeechRecognizeSdk.ets"
)
HARMONY_DEMO = REPO_ROOT / (
    "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/pages/"
    "Index.ets"
)
HARMONY_PREFS = REPO_ROOT / (
    "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/util/"
    "DemoPrefs.ets"
)


class PoliceEnhancementDemoToggleTest(unittest.TestCase):
    def test_android_sdk_and_demo_wire_session_toggle(self) -> None:
        engine = ANDROID_ENGINE.read_text(encoding="utf-8")
        demo = ANDROID_DEMO.read_text(encoding="utf-8")
        prefs = ANDROID_PREFS.read_text(encoding="utf-8")
        layout = ANDROID_LAYOUT.read_text(encoding="utf-8")

        self.assertIn("DingqiaoEngineConfig.enablePoliceEnhancement(params)", engine)
        self.assertIn("if (policeEnhancementEnabled)", engine)
        self.assertIn('extra["enablePoliceEnhancement"]', demo)
        self.assertIn("getPoliceEnhancementEnabled", prefs)
        self.assertIn("setPoliceEnhancementEnabled", prefs)
        self.assertIn("@+id/sw_police_enhancement", layout)

    def test_harmony_sdk_and_demo_wire_session_toggle(self) -> None:
        engine = HARMONY_ENGINE.read_text(encoding="utf-8")
        demo = HARMONY_DEMO.read_text(encoding="utf-8")
        prefs = HARMONY_PREFS.read_text(encoding="utf-8")

        self.assertIn("import { PoliceEnhancePipeline } from 'amphion_police';", engine)
        self.assertIn(
            "strictBooleanParam(params.extraParams, 'enablePoliceEnhancement', true)",
            engine,
        )
        self.assertIn("this.policeEnhancementEnabled", engine)
        self.assertIn("extra['enablePoliceEnhancement']", demo)
        self.assertIn("getPoliceEnhancementEnabled", prefs)
        self.assertIn("setPoliceEnhancementEnabled", prefs)
        self.assertIn("Text('警务增强')", demo)


if __name__ == "__main__":
    unittest.main()
