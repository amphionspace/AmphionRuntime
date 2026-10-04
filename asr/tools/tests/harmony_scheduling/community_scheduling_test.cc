#include "community-scheduling.h"
#include "scope_contract.h"
#include <future>
#include <type_traits>

namespace {
using namespace scheduling_test;
struct OwnedScope : ScopedCommunityScheduling {
  explicit OwnedScope(const CommunityScheduling& policy)
      : ScopedCommunityScheduling(policy, true) {}
};
// Runs on the worker ORT created through the factory, so the level and mask it
// asserts are the ones the encoder would actually execute under.
struct Work {
  std::shared_future<void> release;
  int expected_qos;
  cpu_set_t expected_cpus;
  bool completed = false;
};
void Run(void* opaque) {
  auto& work = *static_cast<Work*>(opaque);
  work.release.wait();
  assert(state.qos == work.expected_qos);
  ExpectMask(work.expected_cpus);
  work.completed = true;
}
}  // namespace

int main(int argc, char**) {
  using namespace scheduling_test;
  FullRequestContract<CommunityScheduling, ScopedCommunityScheduling>();
  OwnedWorkerInheritsCurrentMaskContract<CommunityScheduling, OwnedScope>("community-ort-worker");
  if (argc > 1) return 0;
  static_assert(!std::is_copy_constructible<ScopedCommunityScheduling>::value, "scope owns restoration");
  BorrowedScopeContract<CommunityScheduling, ScopedCommunityScheduling>("community-driver");
  CommunityScheduling policy;
  ParseCommunityScheduling("AmphionQos=user-initiated;AmphionCpuIds=4,5", &policy);
  assert(policy.qos == QOS_USER_INITIATED && policy.cpu_ids == std::vector<int>({4, 5}));
  for (const char *bad : {"AmphionQos=realtime", "AmphionCpuIds=4,4", "AmphionCpuIds=9999",
                         "AmphionCpuIds=4,", "AmphionCpuIds=x", "AmphionCpuIds="}) {
    CommunityScheduling invalid;
    bool rejected = false;
    try { ParseCommunityScheduling(bad, &invalid); }
    catch (const std::exception &) { rejected = true; }
    assert(rejected);
  }
  Reset();
  { ScopedCommunityScheduling scope(policy); }
  ExpectLog("workers=own-qos-inherit-creator-mask-no-later-driver-rebind");

  // A policy with nothing to request must not take over ORT's thread creation,
  // but idle spinning is still given up: it is not part of the thread request.
  Reset();
  CommunityScheduling defaults;
  Ort::SessionOptions untouched;
  ConfigureCommunityScheduling(&untouched, defaults);
  assert(!untouched.create && !untouched.join && untouched.context == nullptr);
  assert(untouched.entries.size() == 1);
  assert(untouched.entries.at("session.inter_op.allow_spinning") == "0");

  // The factory must receive the policy itself, not a copy: ORT keeps this
  // pointer until the workers are joined during session destruction.
  Reset();
  Ort::SessionOptions encoder;
  ConfigureCommunityScheduling(&encoder, policy);
  assert(encoder.create && encoder.join && encoder.context == &policy);

  // Two workers from one session, each carrying the level itself while keeping
  // the inherited mask, so a later screen-state cpuset change stays runnable.
  std::promise<void> release_first, release_second;
  Work first{release_first.get_future().share(), QOS_USER_INITIATED, state.cpus},
       second{release_second.get_future().share(), QOS_USER_INITIATED, state.cpus};
  policy.qos = QOS_USER_INITIATED;
  auto* handle_first = encoder.create(encoder.context, Run, &first);
  auto* handle_second = encoder.create(encoder.context, Run, &second);
  assert(handle_first && handle_second);
  release_second.set_value(); encoder.join(handle_second); assert(second.completed);
  release_first.set_value(); encoder.join(handle_first); assert(first.completed);
  assert(state.qos == QOS_DEFAULT);
  // Workers carry the level but never request a mask, even though this policy
  // names CPUs: the mask they already inherited is the creator's.
  assert(state.requests.empty() && state.sets == 0);
  ExpectLog("poolTag=community-ort-worker");

  // An owned worker has no earlier level to protect, so an unreadable previous
  // QoS is still raised and then reset instead of leaving it process-default.
  Reset();
  CommunityScheduling worker_only;
  worker_only.qos = QOS_USER_INITIATED;
  const auto inherited = state.cpus;
  state.fail_qos_gets = {1};
  {
    ScopedCommunityScheduling owned(worker_only, true);
    assert(state.qos == QOS_USER_INITIATED);
    ExpectMask(inherited);  // Raising the level never narrows the worker.
  }
  assert(state.qos == QOS_DEFAULT && state.qos_resets == 1);
  ExpectMask(inherited);
}
