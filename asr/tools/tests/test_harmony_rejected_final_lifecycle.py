import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY = REPO_ROOT / (
    "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/RejectedFinalLifecycle.ts"
)
ADAPTER = REPO_ROOT / (
    "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
)


class HarmonyRejectedFinalLifecycleTest(unittest.TestCase):
    def test_rejected_final_redacts_postprocessor_source_text(self) -> None:
        runtime = REPO_ROOT / 'asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets'
        delivery = runtime.read_text().split('private deliverSpeakerFinal', 1)[1]
        redaction = delivery[delivery.index('    if (speakerVadReject) {'):
                             delivery.index('    if (this.callbackGate.isClosed()) return;')]
        script = """
          import assert from 'node:assert/strict';
          const speakerVadReject=true;
          const pending={hasEvidence:true,result:{rawText:'一百元',text:'¥100',
            tokens:['一','百','元'],timestamps:[0,.1,.2],tokenConfidences:[.9,.9,.9],
            textNormalization:{text:'¥100',spans:[{sourceBegin:0,sourceEnd:3,textBegin:0,textEnd:4}]},
            speakerScore:.1,isLast:true}};
        """ + redaction + """
          assert.equal(pending.result.rawText,'');assert.equal(pending.result.text,'');
          assert.deepEqual(pending.result.tokens,[]);assert.deepEqual(pending.result.timestamps,[]);
          assert.deepEqual(pending.result.tokenConfidences,[]);
          assert.equal(pending.result.textNormalization,undefined);
          assert.equal(pending.result.isLast,true);assert.equal(pending.result.isTargetSpeaker,false);
          assert.equal(pending.result.speakerScore,.1);
        """
        subprocess.run(['node','--input-type=module','-e',script],check=True,cwd=REPO_ROOT)

    def test_only_last_rejected_final_completes_session(self) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ rejectedFinalCompletesSession }} from {POLICY.as_uri()!r};
            assert.equal(rejectedFinalCompletesSession(false), false);
            assert.equal(rejectedFinalCompletesSession(true), true);
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_non_last_rejected_final_publishes_empty_final_without_completing(self) -> None:
        source = ADAPTER.read_text(encoding="utf-8")
        body = source.split("handleFinalRejected", 1)[1].split("handleAsrError", 1)[0]

        self.assertIn("payload.isFinal = true", body)
        self.assertIn("payload.isLast = result.isLast", body)
        self.assertIn("payload.result = ''", body)
        result_index = body.index("this.listener?.onResult?")
        completion_guard_index = body.index("if (rejectedFinalCompletesSession(result.isLast))")
        self.assertLess(result_index, completion_guard_index)


if __name__ == "__main__":
    unittest.main()
