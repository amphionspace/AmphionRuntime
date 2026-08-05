import pathlib
import subprocess
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]
SDK = ROOT / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
CONFIG = (
    ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/TargetSpeakerEnhancementConfig.ts"
)


class HarmonyTargetSpeakerEnhancementContractTest(unittest.TestCase):
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
