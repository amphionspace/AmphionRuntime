#pragma once
#include "platform_stubs.h"
#include <cassert>
#include <cerrno>
#include <cstdio>
#include <stdexcept>
#include <thread>
#include <type_traits>

namespace scheduling_test {
inline void ExpectLog(const std::string &fragment) {
  const auto logs = Logs();
  for (const auto &line : logs) if (line.find(fragment) != std::string::npos) return;
  for (const auto &line : logs) std::fprintf(stderr, "%s\n", line.c_str());
  std::fprintf(stderr, "missing diagnostic: %s\n", fragment.c_str());
  assert(false);
}

inline void ExpectRequest(size_t index, const cpu_set_t &expected) {
  assert(index < state.requests.size() && "the full request must reach the kernel");
  assert(CPU_EQUAL(&state.requests[index], &expected));
}

template <class Policy, class Scope>
void FullRequestContract() {
  Reset();
  Policy policy;
  policy.cpu_ids = {4, 5, 6, 7, 8, 9, 10, 11};
  state.cpus = Mask({0, 1, 2, 3});
  state.kernel_allowed = Mask({0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11});
  const auto before = state.cpus;
  const auto requested = Mask({4, 5, 6, 7, 8, 9, 10, 11});
  {
    Scope scope(policy);
    ExpectRequest(0, requested);
    ExpectMask(requested);
    assert(state.sets == 1);
    ExpectLog("before=0,1,2,3 currentAfterQos=0,1,2,3 effective=4,5,6,7,8,9,10,11 status=applied errno=0");
  }
  ExpectMask(before);
  ExpectRequest(1, before);
  assert(state.sets == 2);
}

template <class Policy, class Scope>
void OwnedWorkerInheritsCurrentMaskContract(const char *pool_tag) {
  Reset();
  Policy policy;
  policy.cpu_ids = {4, 5, 6, 7};
  const auto before = state.cpus;
  {
    Scope scope(policy);
    ExpectMask(before);
    assert(state.requests.empty());
    assert(state.sets == 0);
  }
  ExpectMask(before);
  assert(state.requests.empty() && state.sets == 0);
  ExpectLog(std::string("poolTag=") + pool_tag);
  ExpectLog("requested=none");
  ExpectLog("status=not-requested");
}

template <class Policy, class Scope>
void BorrowedScopeContract(const char *pool_tag) {
  Reset();
  {
    Policy empty;
    Scope scope(empty);
  }
  assert(state.gets == 0 && state.sets == 0 && state.qos_sets == 0 && Logs().empty());

  // Real mask results and syscall counts, not source-string assertions.
  for (int mode = 0; mode < 3; ++mode) {
    Reset();
    Policy policy;
    policy.cpu_ids = {4, 5};
    state.cpus = mode == 0 ? Mask({1, 4, 5}) : mode == 1 ? Mask({1, 4}) : Mask({1});
    state.kernel_allowed = state.cpus;
    const auto before = state.cpus;
    {
      Scope scope(policy);
      ExpectMask(mode == 0 ? Mask({4, 5}) : mode == 1 ? Mask({4}) : before);
      assert(state.sets == 1);
      ExpectRequest(0, Mask({4, 5}));  // Even disjoint requests reach the kernel.
    }
    ExpectMask(before);
    assert(state.sets == (mode == 2 ? 1 : 2));
    if (mode != 2) ExpectRequest(1, before);
    assert(policy.cpu_ids == std::vector<int>({4, 5}));
    assert(Logs().size() == 1);
    ExpectLog(std::string("poolTag=") + pool_tag);
    ExpectLog("tid=");
    ExpectLog("requested=4,5");
    ExpectLog(mode == 0 ? "before=1,4,5 currentAfterQos=1,4,5 effective=4,5 status=applied errno=0" :
              mode == 1 ? "before=1,4 currentAfterQos=1,4 effective=4 status=readback-adjusted errno=0" :
                          "before=1 currentAfterQos=1 effective=1 status=set-failed errno=" + std::to_string(EINVAL));
    for (const auto &line : Logs()) assert(line.find(" allowed=") == std::string::npos);
  }
  {
    Reset();
    Policy policy;
    policy.cpu_ids = {4, 5};
    const auto before = state.cpus;
    state.fail_gets = {1};
    { Scope scope(policy); ExpectMask(before); }
    assert(state.sets == 0);
    ExpectLog("before=unknown currentAfterQos=unknown effective=unknown status=snapshot-read-failed");
  }
  {
    Reset();
    Policy policy;
    policy.cpu_ids = {4, 5};
    const auto before = state.cpus;
    state.fail_sets = {1};
    { Scope scope(policy); ExpectMask(before); }
    assert(state.sets == 1);
    ExpectLog("status=set-failed errno=" + std::to_string(EPERM));
    for (const auto &line : Logs()) assert(line.find("no-intersection") == std::string::npos);
  }
  for (bool rollback_fails : {false, true}) {
    Reset();
    Policy policy;
    policy.cpu_ids = {4, 5};
    const auto before = state.cpus;
    state.fail_gets = {2};
    if (rollback_fails) state.fail_sets = {2};
    {
      Scope scope(policy);
      ExpectMask(rollback_fails ? Mask({4, 5}) : before);
      assert(state.sets == 2);  // Immediate fallback after unreadable application.
    }
    ExpectMask(before);
    assert(state.sets == 3);  // Exit retries even if the immediate rollback failed.
    ExpectLog("effective=unknown status=readback-failed");
    ExpectLog(rollback_fails ? "fallback=restore-failed" : "fallback=restored-unverified");
  }
  {
    Reset();
    Policy policy;
    policy.cpu_ids = {4, 5};
    const auto before = state.cpus;
    state.adjust_set = true;
    { Scope scope(policy); ExpectMask(Mask({4})); }
    ExpectMask(before);
    ExpectLog("effective=4 status=readback-adjusted");
  }
  // QoS may change current affinity, but never defines the kernel limit.
  // Restore the pre-QoS snapshot after a kernel rejection or affinity failure.
  for (int mode = 0; mode < 5; ++mode) {
    Reset();
    Policy policy;
    policy.qos = QOS_USER_INITIATED;
    policy.cpu_ids = mode == 1 ? std::vector<int>{8} : std::vector<int>{4, 5};
    if (mode == 4) policy.cpu_ids.clear();  // QoS-only also owns its mask side effect.
    state.qos_changes_mask = true;
    const auto before = state.cpus;
    if (mode == 2) state.fail_sets = {1};
    if (mode == 3) state.fail_gets = {2};
    {
      Scope scope(policy);
      assert(state.qos == QOS_USER_INITIATED);
      ExpectMask(mode == 0 || mode == 3 ? Mask({4, 5}) : state.qos_mask);
      if (mode != 4) ExpectRequest(0, mode == 1 ? Mask({8}) : Mask({4, 5}));
    }
    ExpectMask(before);
    assert(state.qos == QOS_DEFAULT && state.qos_sets == 2);
    ExpectLog(mode == 0 ? "currentAfterQos=1,4 effective=4,5 status=applied errno=0" :
              mode == 1 ? "status=set-failed errno=" + std::to_string(EINVAL) :
              mode == 2 ? "status=set-failed errno=" + std::to_string(EPERM) :
              mode == 3 ? "currentAfterQos=unknown effective=4,5 status=applied errno=0" :
                          "status=not-requested");
  }
  for (int failure = 0; failure < 3; ++failure) {
    Reset();
    Policy policy;
    policy.cpu_ids = {4, 5};
    policy.qos = QOS_USER_INITIATED;
    if (failure == 0) state.fail_qos_gets = {1};
    if (failure == 1) state.fail_qos_sets = {1};
    if (failure == 2) state.fail_qos_gets = {2};
    const auto before = state.cpus;
    {
      Scope scope(policy);
      ExpectMask(Mask({4, 5}));  // QoS failures never suppress an affinity request.
      assert(state.qos == (failure == 2 ? QOS_USER_INITIATED : QOS_DEFAULT));
    }
    ExpectMask(before);
    assert(state.qos == QOS_DEFAULT);
    assert(state.qos_resets == 0);  // Borrowed threads never reset unknown QoS.
    if (failure == 0) assert(state.qos_sets == 0);
    ExpectLog(failure == 0 ? "qosStatus=read-failed-skipped" :
              failure == 1 ? "qosStatus=set-failed" : "qosStatus=readback-failed");
  }
  {
    Reset();
    Policy policy;
    policy.cpu_ids = {4, 5};
    policy.qos = QOS_USER_INITIATED;
    state.fail_gets = {1};
    { Scope scope(policy); assert(state.qos == QOS_USER_INITIATED); }
    assert(state.qos == QOS_DEFAULT && state.sets == 0);
    ExpectLog("status=snapshot-read-failed");
  }
  {
    Reset();
    Policy outer, inner;
    outer.cpu_ids = {4, 5}; outer.qos = QOS_USER_INITIATED;
    inner.cpu_ids = {6, 7}; inner.qos = QOS_USER_INTERACTIVE;
    const auto before = state.cpus;
    try {
      Scope scope(outer);
      {
        Scope nested(inner);
        ExpectMask(Mask({6, 7}));  // Nested scopes can expand beyond the outer mask.
        ExpectRequest(0, Mask({4, 5}));
        ExpectRequest(1, Mask({6, 7}));
        assert(state.qos == QOS_USER_INTERACTIVE);
      }
      ExpectMask(Mask({4, 5}));
      ExpectRequest(2, Mask({4, 5}));
      assert(state.qos == QOS_USER_INITIATED);
      throw std::runtime_error("inference failure");
    } catch (const std::runtime_error &) {}
    ExpectMask(before);
    ExpectRequest(3, before);
    assert(state.sets == 4 && state.qos == QOS_DEFAULT);
  }
  {
    Reset();
    Policy policy;
    policy.cpu_ids = {4, 5};
    for (int i = 0; i < 64; ++i) { Scope scope(policy); }
    assert(Logs().size() == 1 && "unchanged hops must stay quiet");
    state.cpus = Mask({1, 4});
    { Scope scope(policy); }
    assert(Logs().size() == 2 && "changed current/effective mask must be observable");
    { Scope scope(policy); }
    assert(Logs().size() == 2);
    std::thread worker([&] { Scope scope(policy); });
    worker.join();
    assert(Logs().size() == 3 && "each actual thread has its own state");
    if constexpr (std::is_copy_constructible<Policy>::value) {
      Policy copy = policy;
      { Scope scope(copy); }
      assert(Logs().size() == 4 && "copied model owns a fresh diagnostic lifetime");
      copy = policy;
      { Scope scope(copy); }
      assert(Logs().size() == 5);
    }
  }
  {
    Reset();
    Policy policy;
    policy.cpu_ids = {4, 5};
    for (int i = 0; i < 3; ++i) {
      state = State{};
      state.fail_sets = {2};  // Scope restore fails, while apply succeeds.
      { Scope scope(policy); }
      ExpectMask(Mask({4, 5}));
    }
    assert(Logs().size() == 2 && "repeated identical restore failures are also quiet");
    ExpectLog("phase=restore");
    ExpectLog("affinityRestoreErrno=");
    state = State{};
    { Scope scope(policy); }
    assert(Logs().size() == 3 && "restore recovery is observable once");
    { Scope scope(policy); }
    assert(Logs().size() == 3);
  }
  {
    Reset();
    Policy policy;
    policy.cpu_ids = {4, 5}; policy.qos = QOS_USER_INITIATED;
    const auto before = state.cpus;
    state.fail_qos_sets = {2};
    { Scope scope(policy); }
    ExpectMask(before);
    assert(state.qos == QOS_USER_INITIATED);
    ExpectLog("qosRestore=-8 affinityRestoreErrno=0");
  }
}
}  // namespace scheduling_test
