#include "platform_stubs.h"
#include <atomic>
#include <cassert>
#include <cerrno>
#include <cstdarg>
#include <cstdio>
#include <mutex>
#include <unistd.h>
#include <hilog/log.h>

namespace scheduling_test {
namespace {
std::mutex log_mutex;
std::vector<std::string> logs;
std::atomic<int> next_tid{100};
}
thread_local State state;
cpu_set_t Mask(std::initializer_list<int> ids) {
  cpu_set_t result{};
  CPU_ZERO(&result);
  for (int cpu : ids) CPU_SET(cpu, &result);
  return result;
}
void Reset() { state = State{}; ClearLogs(); }
void ClearLogs() { std::lock_guard<std::mutex> lock(log_mutex); logs.clear(); }
std::vector<std::string> Logs() { std::lock_guard<std::mutex> lock(log_mutex); return logs; }
void ExpectMask(const cpu_set_t &expected) { assert(CPU_EQUAL(&state.cpus, &expected)); }
}

int amphion_test_gettid() {
  static thread_local int tid = scheduling_test::next_tid.fetch_add(1);
  return tid;
}
int OH_QoS_GetThreadQoS(QoS_Level *value) {
  auto &s = scheduling_test::state;
  if (s.fail_qos_gets.count(++s.qos_gets)) return -7;
  *value = s.qos;
  return 0;
}
int OH_QoS_SetThreadQoS(QoS_Level value) {
  auto &s = scheduling_test::state;
  if (s.fail_qos_sets.count(++s.qos_sets)) return -8;
  s.qos = value;
  if (s.qos_changes_mask) s.cpus = s.qos_mask;
  return 0;
}
int OH_QoS_ResetThreadQoS() {
  auto &s = scheduling_test::state;
  ++s.qos_resets;
  if (s.fail_qos_reset) return -9;
  s.qos = QOS_DEFAULT;
  return 0;
}
int sched_getaffinity(int, unsigned long, cpu_set_t *value) {
  auto &s = scheduling_test::state;
  if (s.fail_gets.count(++s.gets)) { errno = EIO; return -1; }
  *value = s.cpus;
  return 0;
}
int sched_setaffinity(int, unsigned long, const cpu_set_t *value) {
  auto &s = scheduling_test::state;
  s.requests.push_back(*value);
  if (s.fail_sets.count(++s.sets)) { errno = EPERM; return -1; }
  cpu_set_t effective{};
  CPU_AND(&effective, value, &s.kernel_allowed);
  if (CPU_COUNT(&effective) == 0) { errno = EINVAL; return -1; }
  s.cpus = s.adjust_set && s.sets == 1 ? s.adjusted_mask : effective;
  return 0;
}
int OH_LOG_Print(int, int, unsigned, const char *tag, const char *format, ...) {
  std::string portable = format;
  size_t pos;
  while ((pos = portable.find("%{public}")) != std::string::npos) portable.replace(pos, 9, "%");
  va_list args;
  va_start(args, format);
  va_list copy;
  va_copy(copy, args);
  const int size = std::vsnprintf(nullptr, 0, portable.c_str(), copy);
  va_end(copy);
  std::vector<char> message(static_cast<size_t>(size) + 1);
  std::vsnprintf(message.data(), message.size(), portable.c_str(), args);
  va_end(args);
  std::lock_guard<std::mutex> lock(scheduling_test::log_mutex);
  scheduling_test::logs.push_back(std::string(tag) + " " + message.data());
  return 0;
}
