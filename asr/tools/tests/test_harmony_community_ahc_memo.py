"""Hold the AHC pair cache to bitwise-identical labels against a frozen oracle.

The production Ahc caches centroid-linkage distances by live-node slot. A cache
that is wrong in any way changes which pair merges first, so the only acceptable
evidence is identical labels on the same inputs. The oracle in
community_ahc_reference.h is the implementation from before the cache, kept
beside this test for exactly that comparison, so the two run in one binary over
the same vectors.

Both cache paths are exercised: inputs small enough for the private byte budget
take the cached path, and an input past the budget must fall back to the direct
distance and still agree.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CPP = ROOT / "asr/harmony/sdk/src/main/cpp"
ORACLE = Path(__file__).with_name("community_ahc_reference.h")
PRODUCTION = CPP / "community_cluster.h"

PROGRAM = r"""
#include "community_ahc_reference.h"
#include <cstdio>
#include <random>
#include <vector>

using community::Matrix;
using community::Vec;

// Clustered, not uniform: centroid linkage only has interesting merge orders and
// distance inversions when the points actually form groups of varying tightness.
static Matrix Sample(unsigned seed, int points, int dim, int groups) {
  std::mt19937 rng(seed);
  std::normal_distribution<double> jitter(0.0, 0.17);
  std::uniform_real_distribution<double> axis(-1.0, 1.0);
  Matrix centres(groups, Vec(dim));
  for (auto& centre : centres) for (auto& v : centre) v = axis(rng);
  Matrix out;
  out.reserve(points);
  for (int i = 0; i < points; ++i) {
    Vec v = centres[i % groups];
    for (auto& value : v) value += jitter(rng);
    out.push_back(std::move(v));
  }
  return out;
}

int main() {
  struct Case { const char* name; int points; int dim; int groups; };
  // 2049 points is past the 16 MiB budget for a point count this size, so the
  // cache declines and the direct path runs; the rest stay inside it.
  const Case cases[] = {
      {"pair", 2, 8, 2},        {"tiny", 5, 4, 2},
      {"small", 17, 16, 3},     {"ties", 24, 3, 4},
      {"typical", 111, 256, 4}, {"wide", 240, 256, 5},
      {"budget-edge", 2048, 8, 6}, {"over-budget", 2049, 8, 6},
  };
  int failures = 0;
  for (const Case& c : cases) {
    for (unsigned seed = 1; seed <= 3; ++seed) {
      const Matrix x = Sample(seed * 7919u + c.points, c.points, c.dim, c.groups);
      const std::vector<int> produced = community::Ahc(x);
      const std::vector<int> expected = community_ahc_reference::Ahc(x);
      if (produced != expected) {
        std::printf("FAIL %s seed=%u: labels differ\n", c.name, seed);
        ++failures;
        continue;
      }
      if (produced.size() != static_cast<size_t>(c.points)) {
        std::printf("FAIL %s seed=%u: %zu labels for %d points\n",
                    c.name, seed, produced.size(), c.points);
        ++failures;
      }
    }
    std::printf("OK   %-12s points=%-5d dim=%-4d groups=%d\n", c.name, c.points, c.dim, c.groups);
  }
  if (failures) { std::printf("FAILURES %d\n", failures); return 1; }
  std::printf("PASS all cases bitwise identical to the pre-cache oracle\n");
  return 0;
}
"""


class HarmonyCommunityAhcMemoTest(unittest.TestCase):
    def test_cached_distances_keep_labels_identical_to_the_frozen_oracle(self) -> None:
        compiler = shutil.which("clang++") or shutil.which("g++")
        if compiler is None:
            self.skipTest("C++17 compiler unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ahc.cpp").write_text(PROGRAM, encoding="utf-8")
            binary = root / "ahc"
            compiled = subprocess.run(
                [compiler, "-std=c++17", "-O2", f"-I{CPP}", f"-I{ORACLE.parent}",
                 str(root / "ahc.cpp"), "-o", str(binary)],
                capture_output=True, text=True,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=900)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("bitwise identical", run.stdout)
            print(run.stdout.strip())

    def test_the_cache_declines_instead_of_growing_without_bound(self) -> None:
        # The budget is what keeps a large meeting from allocating a quadratic
        # table, so it has to stay a compile-time bound next to the allocation.
        header = PRODUCTION.read_text(encoding="utf-8")
        self.assertIn("constexpr size_t memo_byte_budget = 16u * 1024u * 1024u;", header)
        self.assertIn("entries <= memo_byte_budget / sizeof(double)", header)
        # A failed allocation must leave the direct path usable, not propagate.
        self.assertIn("catch (const std::bad_alloc&)", header)
        self.assertIn("Vec().swap(memo);", header)


if __name__ == "__main__":
    unittest.main()
