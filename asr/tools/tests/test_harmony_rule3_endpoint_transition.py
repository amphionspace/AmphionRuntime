import re
import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY = REPO_ROOT / (
    "asr/harmony/sdk/src/main/ets/com/amphion/asr/NativeEndpointTransitionPolicy.ts"
)
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"


class HarmonyRule3EndpointTransitionTest(unittest.TestCase):
    def test_only_nonempty_rule3_endpoint_preserves_native_stream(self) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ NativeEndpointTransitionPolicy }} from {POLICY.as_uri()!r};

            const HARD = NativeEndpointTransitionPolicy.HARD_RESTART;
            const SOFT = NativeEndpointTransitionPolicy.SOFT_RESET;
            assert.equal(NativeEndpointTransitionPolicy.decide(true, 60320 * 16, 16000, 60), SOFT);
            assert.equal(NativeEndpointTransitionPolicy.decide(true, 59999 * 16, 16000, 60), HARD);
            assert.equal(NativeEndpointTransitionPolicy.decide(false, 60320 * 16, 16000, 60), HARD);
            assert.equal(NativeEndpointTransitionPolicy.decide(true, 60320 * 16, 16000, 0), HARD);
            assert.equal(NativeEndpointTransitionPolicy.decide(true, 60320 * 16, 0, 60), HARD);
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_runtime_tracks_native_samples_and_resets_each_transition(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        self.assertIn("private nativeStreamSamplesAccepted: number = 0;", source)
        self.assertGreaterEqual(
            source.count("this.nativeStreamSamplesAccepted += samples.length;"), 2
        )
        self.assertGreaterEqual(
            source.count("this.nativeStreamSamplesAccepted = 0;"), 2
        )
        self.assertRegex(
            source,
            re.compile(
                r"NativeEndpointTransitionPolicy\.decide\([\s\S]*?"
                r"!this\.speakerVadEnabled && \(endpointResult\.text\.length > 0 \|\| "
                r"endpointResult\.tokens\.length > 0\),[\s\S]*?"
                r"this\.nativeStreamSamplesAccepted,[\s\S]*?"
                r"ASR_SAMPLE_RATE_HZ,[\s\S]*?"
                r"this\.config\.endpointRules\.rule3MinUtteranceLengthSec",
            ),
        )
        self.assertIn("'native-rule3-continuation'", source)


if __name__ == "__main__":
    unittest.main()
