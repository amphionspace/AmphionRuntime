#include <cassert>
#include <cerrno>
#include <future>
#include <stdexcept>
#include "sherpa-onnx/csrc/harmony-scheduling.h"
using namespace sherpa_onnx;
thread_local QoS_Level qos = QOS_DEFAULT;
thread_local cpu_set_t cpus{};
thread_local bool read_qos_fails = false, set_fails = false, read_cpus_fails = false;
thread_local int writes = 0;
thread_local bool qos_updates_cpus = false;
int OH_QoS_GetThreadQoS(QoS_Level *value) { *value = qos; return read_qos_fails ? -1 : 0; }
int OH_QoS_SetThreadQoS(QoS_Level value) {
  ++writes; if (set_fails) return -1; qos = value;
  if (qos_updates_cpus) { CPU_ZERO(&cpus); CPU_SET(0, &cpus); CPU_SET(1, &cpus); CPU_SET(2, &cpus); }
  return 0;
}
int OH_QoS_ResetThreadQoS() { qos = QOS_DEFAULT; return 0; }
int sched_getaffinity(int, unsigned long, cpu_set_t *value) { *value = cpus; return read_cpus_fails ? -1 : 0; }
int sched_setaffinity(int, unsigned long, const cpu_set_t *value) {
  ++writes;
  if (set_fails) { errno = EPERM; return -1; }
  cpus = *value; return 0;
}
struct Work {
  std::shared_future<void> release;
  int expected_qos;
  cpu_set_t expected_cpus;
  bool completed = false;
};
void Run(void *opaque) {
  auto &work = *static_cast<Work *>(opaque);
  work.release.wait();
  assert(qos == work.expected_qos);
  assert(CPU_EQUAL(&cpus, &work.expected_cpus));
  work.completed = true;
}
int main() {
  HarmonyScheduling defaults;
  { ScopedHarmonyScheduling scope(defaults); }
  assert(writes == 0);
  Ort::SessionOptions untouched;
  { HarmonySchedulingConstruction scope(&defaults); ConfigureHarmonyScheduling(&untouched); }
  assert(!untouched.create && untouched.entries.empty());
  HarmonyScheduling a, b;
  a.Parse("cpu;AmphionQos=user-initiated;AmphionCpuIds=2,3;AmphionAllowSpinning=0");
  b.Parse("cpu;AmphionQos=user-interactive;AmphionCpuIds=4");
  CPU_ZERO(&cpus); CPU_SET(0, &cpus);
  const auto original = cpus;
  try {
    ScopedHarmonyScheduling scope(a);
    assert(qos == QOS_USER_INITIATED);
    { ScopedHarmonyScheduling nested(b); assert(qos == QOS_USER_INTERACTIVE); }
    assert(qos == QOS_USER_INITIATED);
    throw std::runtime_error("decode error");
  } catch (const std::runtime_error &) {}
  assert(qos == QOS_DEFAULT && CPU_EQUAL(&original, &cpus));
  set_fails = true;
  { ScopedHarmonyScheduling scope(a); }
  assert(qos == QOS_DEFAULT && CPU_EQUAL(&original, &cpus));
  set_fails = false; read_qos_fails = true; read_cpus_fails = true;
  const int before = writes;
  { ScopedHarmonyScheduling scope(a); }
  assert(writes == before);
  read_qos_fails = false; read_cpus_fails = false;
  // QoS may affect the scheduler's CPU restrictions. Snapshot all original
  // state before changing either setting and restore explicit affinity last.
  qos_updates_cpus = true;
  { ScopedHarmonyScheduling scope(a); }
  assert(qos == QOS_DEFAULT && CPU_EQUAL(&original, &cpus));
  qos_updates_cpus = false;
  Ort::SessionOptions first, second, outside;
  {
    HarmonySchedulingConstruction scope(&a);
    ConfigureHarmonyScheduling(&first);
    { HarmonySchedulingConstruction nested(&b); ConfigureHarmonyScheduling(&second); }
    Ort::SessionOptions restored; ConfigureHarmonyScheduling(&restored);
    assert(restored.context == &a);
  }
  ConfigureHarmonyScheduling(&outside);
  assert(!outside.create && first.entries.size() == 2 && second.entries.empty());
  // Release in reverse order after construction scopes have ended. Policies
  // stay attached to their own recognizer, not to the latest global config.
  std::promise<void> release_a, release_b;
  Work wa{release_a.get_future().share(), QOS_USER_INITIATED, {}},
       wb{release_b.get_future().share(), QOS_USER_INTERACTIVE, {}};
  CPU_SET(2, &wa.expected_cpus); CPU_SET(3, &wa.expected_cpus); CPU_SET(4, &wb.expected_cpus);
  auto ta = first.create(first.context, Run, &wa);
  auto tb = second.create(second.context, Run, &wb);
  assert(ta && tb);
  release_b.set_value(); second.join(tb); assert(wb.completed);
  release_a.set_value(); first.join(ta); assert(wa.completed);
  for (const char *invalid : {"cpu;AmphionQos=invalid", "cpu;AmphionCpuIds=2,2",
       "cpu;AmphionCpuIds=128", "cpu;AmphionCpuIds=2,", "cpu;AmphionCpuIds=-1",
       "cpu;AmphionAllowSpinning=x"}) {
    HarmonyScheduling policy;
    bool rejected = false;
    try { policy.Parse(invalid); } catch (const std::exception &) { rejected = true; }
    assert(rejected);
  }
}
