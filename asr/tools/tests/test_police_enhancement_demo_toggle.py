import unittest
import subprocess
import textwrap
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
HARMONY_POLICY = REPO_ROOT / (
    "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/"
    "PoliceEnhancementPolicy.ts"
)
HARMONY_DEMO = REPO_ROOT / (
    "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/pages/"
    "Index.ets"
)
HARMONY_PREFS = REPO_ROOT / (
    "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/util/"
    "DemoPrefs.ets"
)
HARMONY_SELFCONTAINED_ASSEMBLER = REPO_ROOT / (
    "delivery/harmony-dingqiao/delivery/assemble_selfcontained_dingqiao_har.sh"
)
HARMONY_SELFCONTAINED_VERIFIER = REPO_ROOT / (
    "delivery/harmony-dingqiao/delivery/verify_selfcontained_dingqiao_har.sh"
)


class PoliceEnhancementDemoToggleTest(unittest.TestCase):
    def test_android_sdk_and_demo_wire_session_toggle(self) -> None:
        engine = ANDROID_ENGINE.read_text(encoding="utf-8")
        demo = ANDROID_DEMO.read_text(encoding="utf-8")
        prefs = ANDROID_PREFS.read_text(encoding="utf-8")
        layout = ANDROID_LAYOUT.read_text(encoding="utf-8")

        self.assertIn("DingqiaoEngineConfig.enablePoliceEnhancement(params)", engine)
        self.assertIn("PoliceEnhancementPolicy.finalText(", engine)
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
        self.assertIn("this.policeFinalSession", engine)
        self.assertIn("extra['enablePoliceEnhancement']", demo)
        self.assertIn("getPoliceEnhancementEnabled", prefs)
        self.assertIn("setPoliceEnhancementEnabled", prefs)
        self.assertIn("Text('警务增强')", demo)

    def test_harmony_dingqiao_merges_builtin_police_hotwords_with_user_lexicon(self) -> None:
        engine = HARMONY_ENGINE.read_text(encoding="utf-8")

        self.assertIn("import { PoliceEngineConfig } from 'amphion_police';", engine)
        self.assertIn(
            "config.hotwords = PoliceEngineConfig.effectiveHotwords(\n"
            "    context, parseLexicon(params.extraParams['sysGeneralLexicon']));",
            engine,
        )
        self.assertIn("buildAsrConfig(context, this.params)", engine)
        self.assertIn("buildAsrConfig(this.context, this.params, params,", engine)
        self.assertIn("buildAsrConfig(context, paramsSnapshot)", engine)

    def test_harmony_customer_har_bundles_police_dependency(self) -> None:
        assembler = HARMONY_SELFCONTAINED_ASSEMBLER.read_text(encoding="utf-8")
        verifier = HARMONY_SELFCONTAINED_VERIFIER.read_text(encoding="utf-8")

        self.assertIn('POLICE_HAR="$(har_of ', assembler)
        self.assertIn('"amphion_police": "file:./_bundled/amphion_police"', assembler)
        self.assertIn('"amphion_asr": "file:../amphion_asr"', assembler)
        self.assertIn("self-contained HAR police assets", verifier)
        self.assertNotIn("police enhancement content", verifier)

    def test_harmony_final_text_policy_is_session_scoped(self) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ PoliceFinalSession }} from {HARMONY_POLICY.as_uri()!r};
            let calls = 0;
            const enhance = (raw) => {{ calls += 1; return `${{raw}}-增强`; }};
            const callbacks = [];
            const listener = {{
              onResult: (sessionId, payload) => callbacks.push(
                `${{sessionId}}:result:${{payload.result}}:${{payload.isFinal}}:${{payload.isLast}}`
              ),
              onComplete: (sessionId) => callbacks.push(`${{sessionId}}:complete`),
            }};
            const offPayload = {{ result: '', isFinal: true, isLast: true }};
            new PoliceFinalSession(false, enhance).dispatch(
              offPayload,
              '第一句',
              () => listener.onResult('off', offPayload),
              () => listener.onComplete('off')
            );
            const onPayload = {{ result: '', isFinal: true, isLast: true }};
            new PoliceFinalSession(true, enhance).dispatch(
              onPayload,
              '第二句',
              () => listener.onResult('on', onPayload),
              () => listener.onComplete('on')
            );
            assert.deepEqual(callbacks, [
              'off:result:第一句:true:true',
              'off:complete',
              'on:result:第二句-增强:true:true',
              'on:complete',
            ]);
            assert.equal(calls, 1);
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )
        engine = HARMONY_ENGINE.read_text(encoding="utf-8")
        self.assertIn("import { PoliceFinalSession } from './PoliceEnhancementPolicy';", engine)
        self.assertIn("finalSession.dispatch(", engine)


if __name__ == "__main__":
    unittest.main()
