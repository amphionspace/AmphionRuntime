#include <future>
#include <type_traits>
#include "sherpa-onnx/csrc/harmony-scheduling.h"
#include "scope_contract.h"
using namespace sherpa_onnx;
using namespace scheduling_test;

struct Work {
  std::shared_future<void> release;
  int expected_qos;
  cpu_set_t expected_cpus;
  bool completed = false;
};
void Run(void *opaque) {
  auto &work = *static_cast<Work *>(opaque);
  work.release.wait();
  assert(state.qos == work.expected_qos);
  ExpectMask(work.expected_cpus);
  work.completed = true;
}
struct OwnedScope : ScopedHarmonyScheduling {
  explicit OwnedScope(const HarmonyScheduling& policy) : ScopedHarmonyScheduling(policy, true) {}
};
int main(int argc, char**) {
  FullRequestContract<HarmonyScheduling, ScopedHarmonyScheduling>();
  OwnedWorkerInheritsCurrentMaskContract<HarmonyScheduling, OwnedScope>("asr-ort-worker");
  if (argc > 1) return 0;
  static_assert(!std::is_copy_constructible<HarmonyScheduling>::value, "workers retain the policy address");
  static_assert(!std::is_move_constructible<HarmonyScheduling>::value, "workers retain the policy address");
  static_assert(!std::is_copy_constructible<HarmonySchedulingConstruction>::value, "construction scope owns TLS");
  static_assert(!std::is_copy_constructible<ScopedHarmonyScheduling>::value, "scope owns restoration");
  BorrowedScopeContract<HarmonyScheduling, ScopedHarmonyScheduling>("asr-driver");
  Reset();
  HarmonyScheduling defaults;
  Ort::SessionOptions untouched;
  { HarmonySchedulingConstruction scope(&defaults); ConfigureHarmonyScheduling(&untouched); }
  assert(!untouched.create && untouched.entries.size() == 1);
  assert(untouched.entries.at("session.force_spinning_stop") == "1");
  HarmonyScheduling spin_only;
  spin_only.Parse("cpu;AmphionAllowSpinning=0");
  Ort::SessionOptions idle;
  { HarmonySchedulingConstruction scope(&spin_only); ConfigureHarmonyScheduling(&idle); }
  assert(!idle.create && idle.entries.size() == 3);
  assert(idle.entries.at("session.intra_op.allow_spinning") == "0");
  assert(idle.entries.at("session.inter_op.allow_spinning") == "0");
  { ScopedHarmonyScheduling scope(spin_only); }
  assert(state.sets == 0 && state.qos_sets == 0);  // Spinning remains independent.

  HarmonyScheduling a, b;
  a.Parse("cpu;AmphionQos=user-initiated;AmphionCpuIds=2,3;AmphionAllowSpinning=0");
  b.Parse("cpu;AmphionQos=user-interactive;AmphionCpuIds=4");
  Ort::SessionOptions first, second, outside;
  {
    HarmonySchedulingConstruction scope(&a);
    ConfigureHarmonyScheduling(&first);
    { HarmonySchedulingConstruction nested(&b); ConfigureHarmonyScheduling(&second); }
    Ort::SessionOptions restored; ConfigureHarmonyScheduling(&restored);
    assert(restored.context == &a);
  }
  ConfigureHarmonyScheduling(&outside);
  assert(!outside.create && outside.entries.empty());
  assert(first.entries.size() == 3 && second.entries.size() == 1);
  assert(first.entries.at("session.force_spinning_stop") == "1");
  assert(second.entries.at("session.force_spinning_stop") == "1");
  // Policies remain alive until their workers join; ORT-owned workers inherit
  // the system mask so a later screen-state cpuset change remains runnable.
  std::promise<void> release_a, release_b;
  Work wa{release_a.get_future().share(), QOS_USER_INITIATED, Mask({0, 1, 2, 3, 4, 5, 6, 7})},
       wb{release_b.get_future().share(), QOS_USER_INTERACTIVE, Mask({0, 1, 2, 3, 4, 5, 6, 7})};
  auto ta = first.create(first.context, Run, &wa);
  auto tb = second.create(second.context, Run, &wb);
  assert(ta && tb);
  release_b.set_value(); second.join(tb); assert(wb.completed);
  release_a.set_value(); first.join(ta); assert(wa.completed);
  ExpectLog("poolTag=asr-ort-worker");
  {
    Reset();
    HarmonyScheduling policy;
    policy.qos = QOS_USER_INITIATED;
    state.fail_qos_gets = {1};
    {
      ScopedHarmonyScheduling owned(policy, true);
      assert(state.qos == QOS_USER_INITIATED);
    }
    assert(state.qos == QOS_DEFAULT && state.qos_resets == 1);
  }
  {
    Reset();
    HarmonyScheduling policy;
    policy.qos = QOS_USER_INITIATED;
    state.fail_qos_gets = {1}; state.fail_qos_reset = true;
    { ScopedHarmonyScheduling owned(policy, true); }
    ExpectLog("qosRestore=-9");
  }
  for (const std::string &invalid : std::vector<std::string>{
       "cpu;AmphionQos=invalid", "cpu;AmphionCpuIds=2,2",
       "cpu;AmphionCpuIds=" + std::to_string(CPU_SETSIZE),
       "cpu;AmphionCpuIds=2,", "cpu;AmphionCpuIds=-1",
       "cpu;AmphionAllowSpinning=x"}) {
    HarmonyScheduling policy;
    bool rejected = false;
    try { policy.Parse(invalid); } catch (const std::exception &) { rejected = true; }
    assert(rejected);
  }
}
