"""Run both production native segment decoders against controlled model logits."""
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SOURCES = [
    ROOT / "asr/harmony/sdk/src/main/cpp/speaker_turn_segmenter.cpp",
    ROOT / "asr/android/sdk-dingqiao/src/main/cpp/speaker_turn_segmenter_jni.cpp",
]


class SpeakerTurnOverlapContinuityTest(unittest.TestCase):
    def test_overlap_preserves_continuing_voice_and_real_short_turns(self):
        for source_path in SOURCES:
            with self.subTest(platform=str(source_path.relative_to(ROOT))):
                source = source_path.read_text()
                constants = source[source.index("constexpr int64_t kWindowSamples"):
                                   source.index("\n}", source.index("constexpr int32_t PrimarySpeaker")) + 2]
                segment = source[source.index("  struct Segment {"):
                                 source.index("  };", source.index("  struct Segment {")) + 4]
                decoder = source[source.index("    std::vector<Segment> result;"):
                                 source.index("    return result;") + len("    return result;")]
                harness = r"""
                #include <algorithm>
                #include <array>
                #include <cassert>
                #include <cstdint>
                #include <vector>
                """ + constants + segment + r"""
                std::vector<Segment> Decode(const std::vector<int32_t>& masks) {
                  std::vector<float> samples(kWindowSamples, 0);
                  const int32_t source_offset = 0;
                  std::vector<float> rows(kFrames * kClasses, -10.0F);
                  for (int32_t f = 0; f < kFrames; ++f) {
                    int mask = f < masks.size() ? masks[f] : 0;
                    for (int32_t c = 0; c < kClasses; ++c) {
                      if (ClassToSpeakerMask(c) == mask) rows[f * kClasses + c] = 10.0F;
                    }
                  }
                  const float* logits = rows.data();
                """ + decoder + r"""
                }
                int main() {
                  // Local channel numbers are interchangeable. The continuing
                  // voice must remain primary even when the new voice is lower.
                  for (int a = 0; a < 3; ++a) for (int b = 0; b < 3; ++b) {
                    if (a == b) continue;
                    const int first = 1 << a, other = 1 << b, both = first | other;
                    const auto turns = Decode({first, first, both, first, other, 0, both, 0});
                    assert(turns.size() == 5);
                    assert(turns[0].speaker == a && turns[0].speaker_mask == first);
                    assert(turns[1].speaker == a && turns[1].speaker_mask == both);
                    assert(turns[2].speaker == a && turns[2].speaker_mask == first);
                    // One-frame replies and the real change remain explicit.
                    assert(turns[3].speaker == b && turns[3].speaker_mask == other);
                    assert(turns[3].end - turns[3].start == kReceptiveFieldShift);
                    // A silence breaks continuity; do not copy an earlier voice.
                    assert(turns[4].speaker == std::min(a, b));
                    assert(turns[4].speaker_mask == both);
                    assert(turns[1].start == kReceptiveFieldSize / 2 + 2 * kReceptiveFieldShift);
                    assert(turns[1].end == kReceptiveFieldSize / 2 + 3 * kReceptiveFieldShift);
                    // The first voice actually leaves during an overlapping handoff.
                    const auto handoff = Decode({first, both, other, other});
                    assert(handoff.size() == 3);
                    assert(handoff[1].speaker == a && handoff[1].speaker_mask == both);
                    assert(handoff[2].speaker == b && handoff[2].speaker_mask == other);
                  }
                }
                """
                with tempfile.TemporaryDirectory() as directory:
                    cpp = Path(directory) / "decoder.cpp"
                    executable = Path(directory) / "decoder"
                    cpp.write_text(harness)
                    subprocess.run(["c++", "-std=c++17", str(cpp), "-o", str(executable)],
                                   check=True, capture_output=True, text=True)
                    result = subprocess.run([str(executable)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
