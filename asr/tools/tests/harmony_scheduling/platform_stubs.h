#pragma once
#include <initializer_list>
#include <set>
#include <string>
#include <vector>
#include <sched.h>
#include <qos/qos.h>

namespace scheduling_test {
cpu_set_t Mask(std::initializer_list<int> ids);
struct State {
  cpu_set_t cpus = Mask({0, 1, 2, 3, 4, 5, 6, 7});
  cpu_set_t kernel_allowed = Mask({0, 1, 2, 3, 4, 5, 6, 7});
  QoS_Level qos = QOS_DEFAULT;
  int gets = 0, sets = 0, qos_gets = 0, qos_sets = 0, qos_resets = 0;
  std::set<int> fail_gets, fail_sets, fail_qos_gets, fail_qos_sets;
  bool fail_qos_reset = false, qos_changes_mask = false, adjust_set = false;
  cpu_set_t qos_mask = Mask({1, 4});
  cpu_set_t adjusted_mask = Mask({4});
  std::vector<cpu_set_t> requests;
};
extern thread_local State state;
void Reset();
void ClearLogs();
std::vector<std::string> Logs();
void ExpectMask(const cpu_set_t &expected);
}  // namespace scheduling_test
