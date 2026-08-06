import pathlib
import re
import subprocess
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]
SDK = ROOT / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
ENHANCER = (
    ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/TargetSpeakerEnhancer.ets"
)
CONFIG = (
    ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/TargetSpeakerEnhancementConfig.ts"
)
DEVICE_STRESS = (
    ROOT
    / "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/util/DeviceStressTest.ets"
)


class HarmonyTargetSpeakerEnhancementContractTest(unittest.TestCase):
    def test_missing_separator_reports_the_required_packaged_asset(self) -> None:
        source = ENHANCER.read_text(encoding="utf-8")
        self.assertIn("try {", source)
        self.assertIn("target speaker enhancement model is not bundled", source)
        self.assertIn("amphion-dingqiao/convtasnet_16k.onnx", source)

    def test_device_evidence_records_target_speaker_inputs_and_lifecycle(self) -> None:
        source = DEVICE_STRESS.read_text(encoding="utf-8")
        for function_name in (
            "runTargetSpeakerEnhancementCycle",
            "runTargetSpeakerEnhancementOnStartCycle",
            "runTargetSpeakerEnhancementCancelCycle",
        ):
            start = source.index(f"async function {function_name}")
            next_function = re.search(r"\n(?:async )?function ", source[start + 1 :])
            end = start + 1 + next_function.start() if next_function else len(source)
            body = source[start : end if end >= 0 else len(source)]
            self.assertIn("result.voiceprintIdCount = 1", body, function_name)
            self.assertIn("result.fedFrames =", body, function_name)
            self.assertIn("result.lastFinalsBeforeFinish =", body, function_name)

    def test_active_enhancement_keeps_speaker_vad_enabled(self) -> None:
        sdk = SDK.read_text(encoding="utf-8")
        self.assertIn("!enabled && this.targetSpeakerEnhancementEnabled", sdk)
        self.assertIn("speaker VAD cannot be disabled", sdk)

    def test_public_flag_is_strict_opt_in_and_requires_speaker_vad(self) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ targetSpeakerEnhancementConfig }} from {CONFIG.as_uri()!r};

            assert.deepEqual(targetSpeakerEnhancementConfig({{}}, []), {{ enabled: false }});
            assert.deepEqual(
              targetSpeakerEnhancementConfig({{ enableTargetSpeakerEnhancement: 'true' }}, ['vp']),
              {{ enabled: false }}
            );
            assert.deepEqual(
              targetSpeakerEnhancementConfig({{
                enableTargetSpeakerEnhancement: true,
                enableSpeakerVad: true
              }}, ['vp']),
              {{ enabled: true }}
            );
            assert.throws(
              () => targetSpeakerEnhancementConfig({{ enableTargetSpeakerEnhancement: true }}, ['vp']),
              /enableSpeakerVad=true/
            );
            assert.throws(
              () => targetSpeakerEnhancementConfig({{
                enableTargetSpeakerEnhancement: true,
                enableSpeakerVad: true
              }}, []),
              /voiceprintIds/
            );
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    unittest.main()
