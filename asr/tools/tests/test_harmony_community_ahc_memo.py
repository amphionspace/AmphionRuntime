"""Execute the real AHC against a frozen old oracle; synthetic vectors only."""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CPP = ROOT / 'asr/harmony/sdk/src/main/cpp'
ORACLE = Path(__file__).with_name('community_ahc_reference.h')
RAW = 'double d=0;for(size_t j=0;j<x[0].size();++j)'
MERGE = '    centers[node].resize(x[0].size());for(size_t j=0;j<x[0].size();++j)centers[node][j]=(centers[a][j]*count[a]+centers[b][j]*count[b])/count[node];'
BUDGET = 'constexpr size_t memo_byte_budget = 16u * 1024u * 1024u;'


def observed(header):
    # Observe production expressions without replacing distance/merge behavior.
    entry = '  auto distance=[&](int a,int b){'
    for marker in (entry, RAW, MERGE):
        if header.count(marker) != 1:
            raise AssertionError('AHC observation seam changed: ' + marker)
    header = (header.replace(entry, entry + '\n    ::ahc_probe::BeforeDistance(a,b,cancellation);')
              .replace(RAW, '++::ahc_probe::stats.raw; ' + RAW)
              .replace(MERGE, MERGE + '\n    ::ahc_probe::Merged(node,a,b,d,height[node],count[node],centers[node]);'))
    boundaries = {
        '  int n=x.size();Matrix centers(2*n-1);':
            '  ::allocation_probe::Before(::allocation_probe::Fault::Original);\n',
        '        memo.assign(entries, -1.);':
            '        ::allocation_probe::Before(::allocation_probe::Fault::Score);\n',
        '        memo_slots.assign(centers.size(), -1);':
            '        ::allocation_probe::Before(::allocation_probe::Fault::Slots, memo.capacity());\n',
    }
    for marker, prefix in boundaries.items():
        if header.count(marker) > 1:
            raise AssertionError('Ambiguous allocation observation seam')
        header = header.replace(marker, prefix + marker)
    cleanup = '        std::vector<int>().swap(memo_slots);'
    header = header.replace(cleanup, cleanup + '\n        ::allocation_probe::Released(memo.capacity(), memo_slots.capacity());')
    return header.replace('    if (!memo.empty() && memo[index] >= 0.) return memo[index];',
                          '    if (!memo.empty() && memo[index] >= 0.) { '
                          '++::ahc_probe::stats.hits; '
                          '::ahc_probe::stats.zero_hits += memo[index] == 0.; return memo[index]; }')


PROGRAM = r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <limits>
#include <new>
#include <random>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <vector>
#include "community_cancel.h"
namespace allocation_probe {
enum class Fault { None, Score, Slots, Original };
Fault fault = Fault::None;
bool require_release = false, released = false;
size_t failures = 0, score_attempts = 0;
void Arm(Fault value, size_t) {
  fault = value; failures = 0; released = false;
  require_release = value == Fault::Slots;
}
void Before(Fault stage, size_t score_capacity = 0) {
  if (stage == Fault::Score) ++score_attempts;
  if (fault != stage) return;
  if (stage == Fault::Slots && score_capacity == 0)
    throw std::runtime_error("partial allocation fixture has no real score allocation");
  fault = Fault::None; ++failures; throw std::bad_alloc();
}
void Released(size_t score_capacity, size_t slot_capacity) {
  if (score_capacity || slot_capacity)
    throw std::runtime_error("failed optional memo retained its capacity");
  released = true;
}
}
namespace ahc_probe {
struct Merge {
  int node, a, b, count;
  double distance, height;
  std::vector<double> center;
};
struct Stats {
  size_t queries = 0, raw = 0, hits = 0, zero_hits = 0;
  bool cancel_repeat = false, injected = false;
  size_t merges_at_cancel = 0;
  std::unordered_set<uint64_t> seen;
  std::vector<Merge> merges;
};
Stats stats;
void BeforeDistance(int a, int b, const community::CancellationToken* token) {
  if (allocation_probe::require_release && !allocation_probe::released)
    throw std::runtime_error("failed optional memo retained its capacity");
  ++stats.queries;
  if (stats.cancel_repeat) {
    uint64_t key = (static_cast<uint64_t>(a) << 32) | static_cast<uint32_t>(b);
    if (!stats.seen.insert(key).second) {
      stats.merges_at_cancel = stats.merges.size();
      stats.injected = true; stats.cancel_repeat = false;
      const_cast<community::CancellationToken*>(token)->Cancel();
    }
  }
}
void Merged(int node, int a, int b, double d, double height, int count,
            const std::vector<double>& center) {
  stats.merges.push_back({node, a, b, count, d, height, center});
}
}
#include "community_cluster.h"
#include "community_ahc_reference.h"
using community::Matrix;
using community::Vec;
void Require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}
uint64_t Bits(double value) { uint64_t bits; std::memcpy(&bits, &value, sizeof(bits)); return bits; }
struct Result { std::vector<int> labels; std::string error; ahc_probe::Stats stats; };
Result Run(const Matrix& x, bool old, bool cancel_repeat = false) {
  ahc_probe::stats = {};
  ahc_probe::stats.cancel_repeat = cancel_repeat;
  community::CancellationToken token;
  Result result;
  try {
    result.labels = old ? community_ahc_reference::Ahc(x, &token) : community::Ahc(x, &token);
  } catch (const std::bad_alloc&) { throw; }
    catch (const std::runtime_error& error) { result.error = error.what(); }
  result.stats = std::move(ahc_probe::stats);
  return result;
}
void Equal(const Result& a, const Result& b) {
  Require(a.error == b.error, "error differs from old AHC");
  Require(a.labels == b.labels, "labels differ from old AHC");
  Require(a.stats.queries == b.stats.queries, "distance query order/count changed");
  Require(a.stats.merges.size() == b.stats.merges.size(), "merge count differs");
  for (size_t i = 0; i < a.stats.merges.size(); ++i) {
    const auto& x = a.stats.merges[i]; const auto& y = b.stats.merges[i];
    Require(x.node == y.node && x.a == y.a && x.b == y.b && x.count == y.count, "merge IDs/count differ");
    Require(Bits(x.distance) == Bits(y.distance) && Bits(x.height) == Bits(y.height), "merge score/height bits differ");
    Require(x.center.size() == y.center.size(), "centroid dimensions differ");
    for (size_t j = 0; j < x.center.size(); ++j)
      Require(Bits(x.center[j]) == Bits(y.center[j]), "centroid bits differ");
  }
}
Matrix Angles(std::initializer_list<double> angles) {
  Matrix x;
  for (double angle : angles) x.push_back({std::cos(angle), std::sin(angle)});
  return x;
}
Matrix Generated(int n, int dim, unsigned seed) {
  std::mt19937 random(seed); Matrix x(n, Vec(dim));
  for (auto& row : x) for (auto& value : row)
    value = (static_cast<int>(random() % 2001) - 1000) / 1000.;
  return x;
}
bool middle_slot = false, reversed_slots = false, reused_slot = false;
size_t zero_hits = 0;
void Check(const Matrix& x, bool memo, size_t& raw_before, size_t& raw_after) {
  auto old = Run(x, true); auto current = Run(x, false); Equal(current, old);
  Require(current.stats.queries == current.stats.raw + current.stats.hits, "unobserved distance work");
  zero_hits += current.stats.zero_hits;
  // Classify the real merge trace under the specified inherit-a slot rule.
  std::vector<int> slots(2 * x.size() - 1, -1), uses(x.size());
  std::iota(slots.begin(), slots.begin() + x.size(), 0);
  for (const auto& merge : current.stats.merges) {
    const int sa = slots[merge.a], sb = slots[merge.b];
    middle_slot |= sa > 0 && static_cast<size_t>(sa + 1) < x.size();
    reversed_slots |= sa > sb;
    reused_slot |= ++uses[sa] > 1;
    slots[merge.node] = sa; slots[merge.a] = slots[merge.b] = -1;
  }
  raw_before += old.stats.raw; raw_after += current.stats.raw;
  if (memo && current.error.empty())
    Require(current.stats.raw == (x.size() - 1) * (x.size() - 1), "not exactly one computation per distinct live pair");
  if (!memo) Require(current.stats.raw == old.stats.raw, "budget fallback did not run original distance path");
}
void Parity(bool memo) {
  size_t before = 0, after = 0;
  // The root is below .6, while stale (slot0,slot2) is above .6.
  auto slot0 = Angles({0., .1, .65});
  auto result = Run(slot0, false);
  if (result.labels != std::vector<int>({0, 0, 0})) {
    std::cerr << "slot0 error=" << result.error << " labels=";
    for (int label : result.labels) std::cerr << label << ',';
    for (const auto& merge : result.stats.merges)
      std::cerr << " merge(" << merge.a << ',' << merge.b << ")=" << merge.distance << " height=" << merge.height;
    std::cerr << '\n';
  }
  Require(result.labels == std::vector<int>({0, 0, 0}), "slot0 invalidation crossed the cut");
  Check(slot0, memo, before, after);
  // Initial middle slots merge; later node IDs and slot order are reversed.
  Check(Angles({2.8, 0., .1, 2.7, .2, 1.4, 1.5}), memo, before, after);
  Check(Angles({0., .02, .04, .06, .08, .1, .12, .14}), memo, before, after);
  Matrix tied(8, Vec(4)); for (int i = 0; i < 8; ++i) tied[i][i % 4] = 1.;
  Check(tied, memo, before, after);
  Matrix inversion(3, Vec(3));
  for (int i = 0; i < 3; ++i) {
    double angle = 2 * std::acos(-1.) * i / 3;
    inversion[i] = {std::sqrt(1 - .35 * .35), .35 * std::cos(angle), .35 * std::sin(angle)};
  }
  Check(inversion, memo, before, after);
  Check(Matrix(1, Vec{1., 0.}), memo, before, after);
  Check(Matrix(2, Vec(256)), memo, before, after);
  Check({{1., 0.}, {std::numeric_limits<double>::infinity(), 0.}}, memo, before, after);
  Check({{std::numeric_limits<double>::denorm_min()}, {1.}, {2.}}, memo, before, after);
  // Squared tiny differences round to zero. The old row bound then forces
  // an actual repeated zero-distance query, which must be a legal cache hit.
  const double tiny = .45 * std::sqrt(std::numeric_limits<double>::denorm_min());
  Check({{1., 0.}, {1., 2 * tiny}, {1., tiny}}, memo, before, after);
  for (unsigned seed = 1; seed <= 24; ++seed) Check(Generated(3 + seed, 256, seed), memo, before, after);
  Matrix repeat{{-1., 0.}, {1., 0.}, {1., 1.}};
  auto old = Run(repeat, true); auto current = Run(repeat, false); Equal(current, old);
  Require(old.stats.raw == 5, "repeat fixture no longer exercises old recomputation");
  Require(current.stats.raw == (memo ? 4u : 5u), "memo did not eliminate the repeated distance");
  if (memo) Require(after < before && zero_hits > 0, "distance/zero-hit optimization was not exercised");
  Require(middle_slot && reversed_slots && reused_slot, "slot reuse coverage incomplete");
  std::cout << "PASS parity memo=" << memo << " rawBefore=" << before << " rawAfter=" << after
            << " repeatedPairBefore=" << old.stats.raw << " repeatedPairAfter=" << current.stats.raw
            << " zeroHits=" << zero_hits << " middle/reversed/reused="
            << middle_slot << '/' << reversed_slots << '/' << reused_slot << '\n';
}
void Failures() {
  Matrix x = Generated(32, 256, 1049); const auto old = Run(x, true);
  for (auto fault : {allocation_probe::Fault::Score, allocation_probe::Fault::Slots}) {
    allocation_probe::Arm(fault, x.size());
    auto current = Run(x, false); Equal(current, old);
    Require(allocation_probe::failures == 1, "optional allocation fault was not reached");
    Require(allocation_probe::released, "memo cleanup was not observed");
    Require(current.stats.raw == old.stats.raw, "allocation fallback did not use original distance");
    allocation_probe::require_release = false;
  }
  allocation_probe::Arm(allocation_probe::Fault::Original, x.size());
  bool propagated = false;
  try { (void)Run(x, false); } catch (const std::bad_alloc&) { propagated = true; }
  Require(propagated && allocation_probe::failures == 1, "original allocation failure was swallowed");
  // This is a real N above the production score budget, not a public input cap.
  Matrix large(2049, Vec(4)); for (int i = 0; i < 2049; ++i) large[i][i % 4] = 1.;
  auto expected = Run(large, true);
  allocation_probe::score_attempts = 0;
  auto actual = Run(large, false); Equal(actual, expected);
  Require(allocation_probe::score_attempts == 0, "N2049 attempted an over-budget score allocation");
  Require(actual.error.empty() && actual.labels.size() == 2049, "budget fallback rejected valid input");
  Require(actual.stats.raw == expected.stats.raw, "N2049 did not take original distance path");
  std::cout << "PASS failures score-allocation slot-allocation original-error budget-N2049 scoreAllocationAttempts="
            << allocation_probe::score_attempts << " raw=" << actual.stats.raw << '\n';
}
void Cancellation() {
  Matrix x{{-1., 0.}, {1., 0.}, {1., 1.}};
  auto old = Run(x, true, true); auto current = Run(x, false, true); Equal(current, old);
  Require(current.stats.injected && current.error == "Community operation cancelled", "cache-eligible hit ignored cancellation");
  Require(current.stats.merges.size() == current.stats.merges_at_cancel, "merge advanced after cancelled cache hit");
  Require(current.stats.queries == 5 && current.stats.raw == 4, "cancellation did not occur before the cached repeat");
  std::cout << "PASS cancellation at cached repeat; merges=" << current.stats.merges.size() << '\n';
}
int main(int argc, char** argv) {
  try {
    Require(argc == 3, "mode and expected memo required");
    const std::string mode = argv[1]; const bool memo = std::stoi(argv[2]) != 0;
    if (mode == "parity") Parity(memo);
    else if (mode == "failures") Failures();
    else if (mode == "cancel") Cancellation();
    else throw std::runtime_error("unknown mode");
    return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
'''


class HarmonyCommunityAhcMemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            raise unittest.SkipTest('C++17 compiler unavailable')
        old = ORACLE.read_text()
        body = old[old.index('// Centroid linkage'):old.index('}  // namespace community_ahc_reference')]
        if hashlib.sha256(body.encode()).hexdigest() != 'e808630974af012aa3e67b7bda50466b8a79874b6c0767322fc84b1a99f102ad':
            raise AssertionError('Frozen AHC oracle was changed')
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.binaries = {}
        production = (CPP / 'community_cluster.h').read_text()
        for memo in (True, False):
            directory = Path(cls.directory.name) / ('memo' if memo else 'fallback')
            directory.mkdir()
            header = production
            if not memo:
                # An isolated real-header variant forces the private byte budget
                # to zero. It does not add a product API or replace the algorithm.
                header = header.replace(BUDGET, 'constexpr size_t memo_byte_budget = 0;')
            (directory / 'community_cluster.h').write_text(observed(header))
            (directory / ORACLE.name).write_text(observed(old))
            source = directory / 'ahc.cpp'; source.write_text(PROGRAM)
            binary = directory / 'ahc'
            compiled = subprocess.run([compiler, '-std=c++17', '-O2', '-I', str(directory),
                                       '-I', str(CPP), str(source), '-o', str(binary)],
                                      capture_output=True, text=True, timeout=60)
            if compiled.returncode:
                raise AssertionError(compiled.stdout + compiled.stderr)
            cls.binaries[memo] = binary

    def run_case(self, mode, memo=True):
        result = subprocess.run([str(self.binaries[memo]), mode, str(int(memo))],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS ', result.stdout)
        print(result.stdout.strip())

    def test_merge_centroid_bits_labels_and_repeated_distances(self):
        for memo in (True, False):
            with self.subTest(memo=memo):
                self.run_case('parity', memo)

    def test_optional_allocation_and_budget_fallback_preserve_old_results(self):
        self.run_case('failures')

    def test_cancellation_precedes_a_cache_eligible_hit(self):
        self.run_case('cancel')


if __name__ == '__main__':
    unittest.main()
