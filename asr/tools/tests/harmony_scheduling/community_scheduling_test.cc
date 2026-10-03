#include "community-scheduling.h"
#include "scope_contract.h"
#include <type_traits>

int main(int argc, char**) {
  using namespace scheduling_test;
  FullRequestContract<CommunityScheduling, ScopedCommunityScheduling>();
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
  ExpectLog("workers=inherit-creator-mask-no-later-driver-rebind");
}
