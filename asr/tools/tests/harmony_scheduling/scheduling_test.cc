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
  // Defaults must leave the session options alone. 0.3.19 through 0.3.21 wrote
  // force_spinning_stop here for every session, which cost a wake-up on every
  // decode and 18% of a locked-screen transcript; parking the pools is opt-in.
  Ort::SessionOptions untouched;
  { HarmonySchedulingConstruction scope(&defaults); ConfigureHarmonyScheduling(&untouched); }
  assert(!untouched.create && untouched.entries.empty());
  HarmonyScheduling parked;
  parked.Parse("cpu;AmphionStopIdleSpinning=1");
  assert(parked.stop_idle_spinning);
  Ort::SessionOptions asked;
  { HarmonySchedulingConstruction scope(&parked); ConfigureHarmonyScheduling(&asked); }
  assert(asked.entries.size() == 1);
  assert(asked.entries.at("session.force_spinning_stop") == "1");
  // An explicit 0 is accepted and is the same as not asking.
  HarmonyScheduling off;
  off.Parse("cpu;AmphionStopIdleSpinning=0");
  assert(!off.stop_idle_spinning);
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
  assert(!outside.create && outside.entries.empty());
  // `a` asks for allow_spinning=0, which is two entries; `b` asks for neither
  // spinning option, so it writes nothing. Neither parks the idle pools.
  assert(first.entries.size() == 2 && second.entries.empty());
  assert(first.entries.at("session.intra_op.allow_spinning") == "0");
  assert(first.entries.at("session.inter_op.allow_spinning") == "0");
  assert(first.entries.count("session.force_spinning_stop") == 0);
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
