import json
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
LOADER = ROOT / "asr/tools/tests/ts_extension_loader.mjs"
MANIFEST_POLICY = ROOT / "tts/harmony/sdk/src/main/ets/TtsModelManifest.ts"
FINAL_CONDITION_HEADER = ROOT / "tts/harmony/sdk/src/main/cpp/streaming_final_condition.h"
MODEL_MANIFEST = (
    ROOT
    / "tts/tools/trial-export"
    / "dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop"
    / "0.1.0/manifest.json"
)


class TtsZeroFinalTest(unittest.TestCase):
    def test_manifest_policy_accepts_zero_final_and_preserves_legacy(self) -> None:
        manifest = json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))
        self.assertIs(manifest["stream_final_zero_pad_with_chunk_condition"], True)
        self.assertNotIn("stream_condition_final_model", manifest)

        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ resolveStreamFinalConditionPolicy }} from {MANIFEST_POLICY.as_uri()!r};

            assert.deepEqual(resolveStreamFinalConditionPolicy(true, undefined), {{
              useChunkConditionForFinal: true,
              finalModelFile: ''
            }});
            assert.equal(resolveStreamFinalConditionPolicy(false, undefined), undefined);
            assert.deepEqual(resolveStreamFinalConditionPolicy(
              false, 'lits_stream_condition_final.onnx'), {{
                useChunkConditionForFinal: false,
                finalModelFile: 'lits_stream_condition_final.onnx'
              }});
            """
        )
        subprocess.run(
            [
                "node",
                "--experimental-strip-types",
                "--experimental-loader",
                LOADER.as_uri(),
                "--input-type=module",
                "-e",
                script,
            ],
            cwd=ROOT,
            check=True,
        )

    def test_native_final_condition_plan_pads_only_zero_final(self) -> None:
        source = textwrap.dedent(
            f"""
            #include <cassert>
            #include <vector>
            #include "{FINAL_CONDITION_HEADER}"

            int main() {{
              const auto legacy = BuildStreamingFinalConditionPlan(false, 5, 3);
              assert(!legacy.use_chunk_condition);
              assert(legacy.condition_frames == 5);

              const auto zero_final = BuildStreamingFinalConditionPlan(true, 5, 3);
              assert(zero_final.use_chunk_condition);
              assert(zero_final.condition_frames == 8);

              std::vector<float> frames = {{1.0f, 2.0f, 3.0f, 4.0f}};
              PadStreamingFinalConditionFrames(&frames, true, 2, 2);
              assert(frames.size() == 8);
              assert(frames[3] == 4.0f);
              assert(frames[4] == 0.0f);
              assert(frames[7] == 0.0f);
              return 0;
            }}
            """
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_path = temp_path / "zero_final_test.cpp"
            binary_path = temp_path / "zero_final_test"
            source_path.write_text(source, encoding="utf-8")
            subprocess.run(
                ["c++", "-std=c++17", str(source_path), "-o", str(binary_path)],
                cwd=ROOT,
                check=True,
            )
            subprocess.run([str(binary_path)], cwd=ROOT, check=True)


if __name__ == "__main__":
    unittest.main()
