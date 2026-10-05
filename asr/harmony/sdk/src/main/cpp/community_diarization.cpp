#include "community_cluster.h"
#include "community_fbank.h"
#include "onnxruntime_cxx_api.h"
#ifndef __ANDROID__
#include <node_api.h>
#endif
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <chrono>
#include <cstring>
#include <iomanip>
#include <memory>
#include <limits>
#ifndef __ANDROID__
#include <rawfile/raw_file_manager.h>
#endif
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#if defined(__OHOS__)
// Platform headers stay outside every namespace; including them from within one
// is ill-formed and only stayed hidden because the host slices included them
// separately before pasting the production block.
#include <cerrno>
#include <hilog/log.h>
#include <sched.h>
#include <qos/qos.h>
#include <unistd.h>
#endif

namespace {
using Clock = std::chrono::steady_clock;
double Milliseconds(Clock::time_point start) {
  return std::chrono::duration<double, std::milli>(Clock::now() - start).count();
}

// Community encoder compute budget, independent of the ASR recognizer pool.
// Harmony's pinned U8/S8 per-channel INT8 graph uses the ORT CPU pool; Android's
// FP32 graph uses XNNPACK. Both receive the caller's budget below.
constexpr int kDefaultEncoderThreads = 2;
constexpr int kMaxEncoderThreads = 8;

#if defined(__OHOS__)
namespace {
// The engine-wide scheduling request the ASR recognizer already receives. The
// role encoder owns a second compute pool, so it needs its own copy: the ASR
// policy reaches that pool only when it is passed here as well.
struct CommunitySchedulingReports {
  std::mutex mutex;
  std::unordered_map<int, std::array<std::string, 2>> last;
  CommunitySchedulingReports() = default;
  // A copied model policy starts a new diagnostic lifetime, with no references
  // to the Work or model it was copied from.
  CommunitySchedulingReports(const CommunitySchedulingReports&) {}
  CommunitySchedulingReports& operator=(const CommunitySchedulingReports&) {
    std::lock_guard<std::mutex> lock(mutex);
    last.clear();
    return *this;
  }
};
struct CommunityScheduling {
  int qos = -1;
  std::vector<int> cpu_ids;
  mutable CommunitySchedulingReports reports;
  bool has_thread_policy() const { return qos >= 0 || !cpu_ids.empty(); }
};

void ParseCommunityScheduling(const std::string& provider, CommunityScheduling* out) {
  std::istringstream entries(provider);
  std::string entry;
  while (std::getline(entries, entry, ';')) {
    const auto separator = entry.find('=');
    if (separator == std::string::npos) continue;
    const auto key = entry.substr(0, separator);
    const auto value = entry.substr(separator + 1);
    if (key == "AmphionQos") {
      if (value == "user-initiated") out->qos = QOS_USER_INITIATED;
      else if (value == "user-interactive") out->qos = QOS_USER_INTERACTIVE;
      else throw std::runtime_error("invalid Community scheduling QoS");
    } else if (key == "AmphionCpuIds") {
      if (value.empty() || value.back() == ',')
        throw std::runtime_error("empty Community scheduling CPU id");
      std::istringstream ids(value);
      std::string id;
      while (std::getline(ids, id, ',')) {
        if (id.empty() || id.find_first_not_of("0123456789") != std::string::npos)
          throw std::runtime_error("invalid Community scheduling CPU id");
        const int cpu = std::stoi(id);
        if (cpu < 0 || cpu >= CPU_SETSIZE)
          throw std::runtime_error("Community scheduling CPU id out of range");
        for (int existing : out->cpu_ids) {
          if (existing == cpu) throw std::runtime_error("duplicate Community scheduling CPU id");
        }
        out->cpu_ids.push_back(cpu);
      }
    }
  }
}

std::string CommunityCpuMask(const cpu_set_t& cpus, bool known) {
  if (!known) return "unknown";
  std::string result;
  for (int cpu = 0; cpu < CPU_SETSIZE; ++cpu) {
    if (!CPU_ISSET(cpu, &cpus)) continue;
    if (!result.empty()) result += ',';
    result += std::to_string(cpu);
  }
  return result.empty() ? "none" : result;
}

bool CommunityCpuMasksEqual(const cpu_set_t& left, const cpu_set_t& right) {
  for (int cpu = 0; cpu < CPU_SETSIZE; ++cpu) {
    if (!!CPU_ISSET(cpu, &left) != !!CPU_ISSET(cpu, &right)) return false;
  }
  return true;
}

// Two roles. On a borrowed driver thread this applies affinity and QoS for the
// duration of one call. On an ORT worker this thread created itself, it wraps the
// whole worker lifetime and carries the QoS that pthread_create does not inherit;
// the mask already came from the creating thread, so the worker never re-requests
// one. Existing workers are still not rebound by a later driver scope.
class ScopedCommunityScheduling {
 public:
  explicit ScopedCommunityScheduling(const CommunityScheduling& policy, bool owned_thread = false)
      : policy_(policy), owned_thread_(owned_thread),
        pool_tag_(owned_thread ? "community-ort-worker" : "community-driver") {
    if (!policy.has_thread_policy()) return;
    if (!owned_thread_) {
      for (int cpu : policy.cpu_ids) CPU_SET(cpu, &requested_cpus_);
    }
    // Current affinity is only a snapshot, not the system cpuset limit.
    // Submit the complete request and let the kernel enforce its restrictions.
    have_previous_ = sched_getaffinity(0, sizeof(previous_cpus_), &previous_cpus_) == 0;
    snapshot_error_ = have_previous_ ? 0 : errno;
    current_after_qos_cpus_ = previous_cpus_;
    have_current_after_qos_ = have_previous_;
    if (policy.qos >= 0) {
      qos_result_ = OH_QoS_GetThreadQoS(&previous_qos_);
      const int before = qos_result_;
      // A borrowed runtime thread never loses an unknown previous QoS. An owned
      // worker has no earlier policy to protect, so an unreadable level is not a
      // reason to leave it in whatever group the process was demoted to.
      if (before == 0 || owned_thread_) {
        effective_qos_ = before == 0 ? static_cast<int>(previous_qos_) : -1;
        qos_result_ = OH_QoS_SetThreadQoS(static_cast<QoS_Level>(policy.qos));
        restore_qos_ = qos_result_ == 0 && before == 0;
        reset_qos_ = qos_result_ == 0 && before != 0;
        qos_status_ = qos_result_ == 0 ? "applied" : "set-failed";
        if (restore_qos_ || reset_qos_) {
          // QoS itself may change affinity, even when the later CPU request
          // fails. Restore that side effect as well.
          restore_cpus_ = have_previous_;
          have_current_after_qos_ = sched_getaffinity(0, sizeof(current_after_qos_cpus_), &current_after_qos_cpus_) == 0;
          affinity_error_ = have_current_after_qos_ ? 0 : errno;
          QoS_Level effective;
          qos_result_ = OH_QoS_GetThreadQoS(&effective);
          effective_qos_ = qos_result_ == 0 ? static_cast<int>(effective) : -1;
          if (qos_result_ != 0) qos_status_ = "readback-failed";
        }
      } else {
        // Never overwrite an unknown policy on a borrowed runtime thread.
        qos_status_ = "read-failed-skipped";
      }
    }
    effective_cpus_ = current_after_qos_cpus_;
    have_effective_ = have_current_after_qos_;
    if (!owned_thread_ && !policy.cpu_ids.empty()) {
      if (!have_previous_) {
        affinity_status_ = "snapshot-read-failed";
        affinity_error_ = snapshot_error_;
      } else if (sched_setaffinity(0, sizeof(requested_cpus_), &requested_cpus_) != 0) {
        affinity_status_ = "set-failed";
        affinity_error_ = errno;
      } else {
        // Own restoration immediately after a successful set, even if the
        // readback fails. An immediate rollback is retried on scope exit.
        restore_cpus_ = true;
        affinity_error_ = 0;
        have_effective_ = sched_getaffinity(0, sizeof(effective_cpus_), &effective_cpus_) == 0;
        if (!have_effective_) {
          affinity_status_ = "readback-failed";
          affinity_error_ = errno;
          const int result = sched_setaffinity(0, sizeof(previous_cpus_), &previous_cpus_);
          rollback_error_ = result == 0 ? 0 : errno;
          fallback_ = result == 0 ? "restored-unverified" : "restore-failed";
        } else if (!CommunityCpuMasksEqual(requested_cpus_, effective_cpus_)) {
          affinity_status_ = "readback-adjusted";
        } else {
          affinity_status_ = "applied";
        }
      }
    }
    Report(false);
  }
  ~ScopedCommunityScheduling() {
    const int qos_result = restore_qos_ ? OH_QoS_SetThreadQoS(previous_qos_) :
        (reset_qos_ ? OH_QoS_ResetThreadQoS() : 0);
    // QoS restoration comes first because it can also alter the thread mask.
    const int affinity_result = restore_cpus_ ? sched_setaffinity(0, sizeof(previous_cpus_), &previous_cpus_) : 0;
    const int affinity_error = affinity_result == 0 ? 0 : errno;
    if (policy_.has_thread_policy()) Report(true, qos_result, affinity_error);
  }
  ScopedCommunityScheduling(const ScopedCommunityScheduling&) = delete;
  ScopedCommunityScheduling& operator=(const ScopedCommunityScheduling&) = delete;

 private:
  void Report(bool restoring, int qos_restore = 0, int affinity_restore = 0) noexcept {
    try {
      const int tid = gettid();
      auto& reports = policy_.reports;
      std::lock_guard<std::mutex> lock(reports.mutex);
      auto& last = reports.last[tid][restoring ? 1 : 0];
      // Successful scope restoration is quiet unless it recovers from a failure.
      if (restoring && qos_restore == 0 && affinity_restore == 0 && last.empty()) return;
      std::ostringstream state;
      state << "requested=" << CommunityCpuMask(requested_cpus_, true)
            << " before=" << CommunityCpuMask(previous_cpus_, have_previous_)
            << " currentAfterQos=" << CommunityCpuMask(current_after_qos_cpus_, have_current_after_qos_)
            << " effective=" << CommunityCpuMask(effective_cpus_, have_effective_)
            << " status=" << affinity_status_ << " errno=" << affinity_error_
            << " snapshotErrno=" << snapshot_error_
            << " fallback=" << fallback_ << " rollbackErrno=" << rollback_error_
            << " qosRequested=" << policy_.qos << " qosEffective=" << effective_qos_
            << " qosStatus=" << qos_status_ << " qosResult=" << qos_result_;
      if (restoring) state << " maskPhase=apply qosRestore=" << qos_restore << " affinityRestoreErrno=" << affinity_restore;
      const auto message = state.str();
      if (last == message) return;
      last = message;
      OH_LOG_Print(LOG_APP, LOG_INFO, 0x6666, "AmphionScheduling",
                   "poolTag=%{public}s tid=%{public}d policy=%{public}p phase=%{public}s %{public}s "
                   "workers=own-qos-inherit-creator-mask-no-later-driver-rebind",
                   pool_tag_, tid, static_cast<const void*>(&policy_),
                   restoring ? "restore" : "apply", message.c_str());
    } catch (...) {
      // Diagnostics must not break restoration or propagate from a destructor.
    }
  }
  const CommunityScheduling& policy_;
  const bool owned_thread_ = false;
  const char* pool_tag_ = "community-driver";
  cpu_set_t previous_cpus_{}, requested_cpus_{}, current_after_qos_cpus_{}, effective_cpus_{};
  QoS_Level previous_qos_{};
  bool restore_qos_ = false, reset_qos_ = false, restore_cpus_ = false;
  bool have_previous_ = false, have_current_after_qos_ = false, have_effective_ = false;
  const char* affinity_status_ = "not-requested";
  const char* qos_status_ = "not-requested";
  const char* fallback_ = "none";
  int snapshot_error_ = 0, affinity_error_ = 0, rollback_error_ = 0, qos_result_ = 0, effective_qos_ = -1;
};

// ORT creates its intra-op workers through this factory, so each worker can carry
// the requested QoS itself. pthread_create does not inherit a QoS level, which is
// why a driver-thread-only request never reached the threads that run the encoder.
OrtCustomThreadHandle CreateCommunityWorker(void* opaque, OrtThreadWorkerFn work, void* param) {
  const auto* policy = static_cast<const CommunityScheduling*>(opaque);
  try {
    auto* thread = new std::thread([policy, work, param] {
      // Held for the worker's whole life, not one call: the scope is what keeps
      // the level applied while ORT reuses this thread across windows.
      ScopedCommunityScheduling scope(*policy, true);
      work(param);
    });
    return reinterpret_cast<OrtCustomThreadHandle>(thread);
  } catch (...) {
    // ORT owns failure handling; never let an exception cross its C callback.
    return nullptr;
  }
}

void JoinCommunityWorker(OrtCustomThreadHandle handle) {
  auto* thread = reinterpret_cast<std::thread*>(const_cast<OrtCustomHandleType*>(handle));
  if (thread != nullptr) {
    thread->join();
    delete thread;
  }
}

// Only for sessions that actually own an intra-op pool; a one-thread session runs
// on its caller and never reaches this factory. `policy` must outlive every session
// configured here: ORT joins these workers while a session is destroyed, and each
// join runs the worker's scope exit. The caller keeps the existing per-session
// intra-op spinning choice; this adds the inter-op half the recognizer also sets.
void ConfigureCommunityScheduling(Ort::SessionOptions* options, const CommunityScheduling& policy) {
  options->AddConfigEntry("session.inter_op.allow_spinning", "0");
  if (!policy.has_thread_policy()) return;
  options->SetCustomCreateThreadFn(CreateCommunityWorker);
  options->SetCustomThreadCreationOptions(const_cast<CommunityScheduling*>(&policy));
  options->SetCustomJoinThreadFn(JoinCommunityWorker);
}
}  // namespace
#else
namespace {
struct CommunityScheduling {
  int qos = -1;
  std::vector<int> cpu_ids;
  bool has_thread_policy() const { return false; }
};
inline void ParseCommunityScheduling(const std::string& provider, CommunityScheduling* out) {
  (void)out;
  if (!provider.empty()) {
    throw std::runtime_error("Community scheduling requires an OHOS runtime");
  }
}
class ScopedCommunityScheduling {
 public:
  explicit ScopedCommunityScheduling(const CommunityScheduling&, bool = false) {}
};
// Android keeps ORT's own worker creation and its existing spinning policy; the
// QoS and affinity request this mirrors is an OHOS-only capability. Templated so
// the stub needs no session type of its own: host slices paste this block without
// an ORT declaration and never call it.
template <class Options>
inline void ConfigureCommunityScheduling(Options*, const CommunityScheduling&) {}
}  // namespace
#endif

#ifndef __ANDROID__
template <typename T>
std::vector<T> CopyArray(napi_env env, napi_value value, napi_typedarray_type expected,
                         size_t max_elements = std::numeric_limits<size_t>::max()) {
  napi_typedarray_type type;
  size_t length = 0, offset = 0;
  void* data = nullptr;
  napi_value buffer = nullptr, byte_length = nullptr;
  uint32_t bytes = 0;
  if (napi_get_typedarray_info(env, value, &type, &length, &data, &buffer, &offset) != napi_ok ||
      type != expected || napi_get_named_property(env, value, "byteLength", &byte_length) != napi_ok ||
      napi_get_value_uint32(env, byte_length, &bytes) != napi_ok || bytes % sizeof(T)) {
    throw std::runtime_error("invalid Community typed array");
  }
  void* buffer_data = nullptr;
  size_t buffer_bytes = 0;
  if (napi_get_arraybuffer_info(env, buffer, &buffer_data, &buffer_bytes) != napi_ok ||
      offset > buffer_bytes || bytes > buffer_bytes - offset) {
    throw std::runtime_error("Community typed array exceeds its backing buffer");
  }
  const size_t elements = bytes / sizeof(T);
  // Match the existing Harmony bridge: affected releases report bytes here,
  // while standard Node-API reports elements. Keep valid subarray views intact.
  if (length != elements && length != bytes) {
    throw std::runtime_error("inconsistent Community typed array length");
  }
  if (elements > max_elements) {
    throw std::runtime_error("Community typed array exceeds sample limit");
  }
  std::vector<T> result(elements);
  if (bytes) std::memcpy(result.data(), data, bytes);
  return result;
}

napi_value NormalizeCommunityPcm16Window(napi_env env, napi_callback_info info) {
  try {
    size_t count = 1;
    napi_value input = nullptr;
    if (napi_get_cb_info(env, info, &count, &input, nullptr, nullptr) != napi_ok || count != 1) {
      throw std::runtime_error("normalizeCommunityPcm16Window requires one Int16Array");
    }
    constexpr size_t window_samples = 160000;
    const auto pcm = CopyArray<int16_t>(env, input, napi_int16_array, window_samples);
    napi_value buffer = nullptr, result = nullptr;
    void* data = nullptr;
    if (napi_create_arraybuffer(env, window_samples * sizeof(float), &data, &buffer) != napi_ok ||
        data == nullptr) {
      throw std::runtime_error("Community PCM output allocation failed");
    }
    if (napi_create_typedarray(env, napi_float32_array, window_samples, buffer, 0, &result) != napi_ok) {
      throw std::runtime_error("Community PCM output view creation failed");
    }
    auto* output = static_cast<float*>(data);
    std::fill_n(output, window_samples, 0.0f);
    for (size_t i = 0; i < pcm.size(); ++i) output[i] = static_cast<float>(pcm[i]) / 32768.0f;
    return result;
  } catch (const std::exception& error) {
    bool pending = false;
    if (napi_is_exception_pending(env, &pending) != napi_ok || pending) return nullptr;
    if (napi_throw_error(env, nullptr, error.what()) != napi_ok) return nullptr;
    return nullptr;
  }
}

#endif

struct Window {
  std::vector<float> segments, embeddings;
  // [window, channel, begin frame, end frame) for each contiguous clean run.
  std::vector<float> run_embeddings;
  std::vector<float> run_ranges;
  std::vector<float> run_rms;
  double segmentation_ms = 0, feature_ms = 0, embedding_ms = 0;
};


class CommunityCancellation {
 public:
  const community::CancellationToken* token() const noexcept { return &token_; }
  bool IsCancelled() const noexcept { return token_.IsCancelled(); }

  bool Register(Ort::RunOptions* options) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (token_.IsCancelled()) return false;
    active_.push_back(options);
    return true;
  }

  void Unregister(Ort::RunOptions* options) noexcept {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto found = std::find(active_.begin(), active_.end(), options);
    if (found != active_.end()) active_.erase(found);
  }

  void Cancel() noexcept {
    std::lock_guard<std::mutex> lock(mutex_);
    token_.Cancel();
    for (auto* options : active_) {
      try {
        options->SetTerminate();
      } catch (...) {
        // The CPU cancellation checks still make progress when an execution
        // provider rejects SetTerminate; never throw across the N-API callback.
      }
    }
  }

 private:
  community::CancellationToken token_;
  std::mutex mutex_;
  std::vector<Ort::RunOptions*> active_;
};

template <typename Function>
auto RunCommunityOrt(const std::shared_ptr<CommunityCancellation>& cancellation,
                     Function&& function) {
  if (!cancellation) return function(Ort::RunOptions{nullptr});
  Ort::RunOptions options;
  if (!cancellation->Register(&options)) {
    throw std::runtime_error("Community operation cancelled");
  }
  try {
    auto result = function(options);
    cancellation->Unregister(&options);
    return result;
  } catch (...) {
    cancellation->Unregister(&options);
    throw;
  }
}

#ifndef __ANDROID__
std::vector<uint8_t> ReadCommunityAsset(NativeResourceManager* manager, const char* name) {
  std::unique_ptr<RawFile, decltype(&OH_ResourceManager_CloseRawFile)> file(
    OH_ResourceManager_OpenRawFile(manager, name), OH_ResourceManager_CloseRawFile);
  if (!file) throw std::runtime_error(std::string("Community model asset unavailable: ") + name);
  const long size = OH_ResourceManager_GetRawFileSize(file.get());
  if (size <= 0) throw std::runtime_error("Community model asset is empty");
  std::vector<uint8_t> bytes(static_cast<size_t>(size));
  size_t offset = 0;
  while (offset < bytes.size()) {
    const size_t remaining = bytes.size() - offset;
    const int read = OH_ResourceManager_ReadRawFile(file.get(), bytes.data() + offset,
      std::min(remaining, static_cast<size_t>(std::numeric_limits<int>::max())));
    if (read <= 0 || static_cast<size_t>(read) > remaining) {
      throw std::runtime_error("Community model asset read failed");
    }
    offset += static_cast<size_t>(read);
  }
  return bytes;
}

#endif

class Model {
 public:
  Model(const std::vector<uint8_t>& segmentation, const std::vector<uint8_t>& encoder,
        const std::vector<uint8_t>& pooling,
        const std::vector<uint8_t>& feature, const std::vector<uint8_t>& plda,
        int encoder_threads = kDefaultEncoderThreads,
        const CommunityScheduling& scheduling = CommunityScheduling())
      : env_(ORT_LOGGING_LEVEL_WARNING, "amphion-community"), scheduling_(scheduling) {
    if (encoder_threads < 1 || encoder_threads > kMaxEncoderThreads) {
      throw std::runtime_error("Community encoder threads must be in [1, 8]");
    }
    if (feature.size() != (400 + 80 * 257) * sizeof(float)) {
      throw std::runtime_error("invalid Community feature constants");
    }
    constants_.resize(feature.size() / sizeof(float));
    std::memcpy(constants_.data(), feature.data(), feature.size());
    constexpr size_t doubles = 256 + 128 + 256 * 128 + 128 + 128 * 128 + 128;
    if (plda.size() != 16 + doubles * sizeof(double)) throw std::runtime_error("invalid Community PLDA");
    uint32_t header[4];
    std::memcpy(header, plda.data(), sizeof(header));
    if (header[0] != 0x434d504c || header[1] != 1 || header[2] != 256 || header[3] != 128) {
      throw std::runtime_error("unsupported Community PLDA format");
    }
    size_t pos = 16;
    auto vector = [&](size_t n) {
      community::Vec v(n);
      std::memcpy(v.data(), plda.data() + pos, n * sizeof(double));
      pos += n * sizeof(double);
      return v;
    };
    plda_.mean1 = vector(256);
    plda_.mean2 = vector(128);
    for (int row = 0; row < 256; ++row) plda_.lda.push_back(vector(128));
    plda_.mu = vector(128);
    for (int row = 0; row < 128; ++row) plda_.transform.push_back(vector(128));
    plda_.phi = vector(128);
    Ort::SessionOptions segmentation_options;
    segmentation_options.SetExecutionMode(ExecutionMode::ORT_SEQUENTIAL);
    segmentation_options.SetInterOpNumThreads(1);
    segmentation_options.DisableCpuMemArena();
    segmentation_options.DisableMemPattern();
    segmentation_options.SetIntraOpNumThreads(2);
    segmentation_options.AddConfigEntry("session.intra_op.allow_spinning", "0");
    // The policy member, never the construction copy below: these workers outlive
    // this constructor and are joined when the session is destroyed.
    ConfigureCommunityScheduling(&segmentation_options, scheduling_);
    CommunityScheduling construction_scheduling = scheduling_;
#if !defined(__OHOS__)
    construction_scheduling.cpu_ids.clear();
#endif
    // Harmony pools inherit the effective requested mask; the scope restores
    // this borrowed driver after construction, including exception paths.
    ScopedCommunityScheduling construction_scope(construction_scheduling);
    segmentation_ = Ort::Session(env_, segmentation.data(), segmentation.size(), segmentation_options);
    Ort::SessionOptions pooling_options;
    pooling_options.SetExecutionMode(ExecutionMode::ORT_SEQUENTIAL);
    pooling_options.SetInterOpNumThreads(1);
    pooling_options.DisableCpuMemArena();
    pooling_options.DisableMemPattern();
    pooling_options.SetIntraOpNumThreads(1);
    pooling_ = Ort::Session(env_, pooling.data(), pooling.size(), pooling_options);
    Ort::SessionOptions options;
    options.SetExecutionMode(ExecutionMode::ORT_SEQUENTIAL);
    options.SetInterOpNumThreads(1);
    options.DisableCpuMemArena();
    options.DisableMemPattern();
#if defined(__OHOS__)
    // XNNPACK is deliberately not registered for the Harmony encoder, and the
    // reason holds for either INT8 representation. The pinned graph pairs UINT8
    // activations with per-channel INT8 weights, which ORT 1.16.3's XNNPACK
    // rejects outright (`we do not handle u8s8`), so registering it would only
    // build a pthreadpool that claims no operator. A signed-activation graph
    // would be claimed on all of its convolutions instead, which is worse here:
    // that pool is created inside the EP and reaches neither the worker factory
    // below nor the spinning switch, so it would put the dominant compute back
    // on threads no scheduling request can describe. Keeping the encoder on the
    // CPU EP is what makes the caller's QoS reach the threads that run it.
    options.SetIntraOpNumThreads(encoder_threads);
    options.AddConfigEntry("session.intra_op.allow_spinning", "0");
    ConfigureCommunityScheduling(&options, scheduling_);
#else
    // Android retains the FP32 encoder and its XNNPACK compute pool. The
    // from-buffer API also accepts FP32 encoders, which this provider serves.
    options.SetIntraOpNumThreads(1);
    options.AppendExecutionProvider("XNNPACK",
      {{"intra_op_num_threads", std::to_string(encoder_threads)}});
#endif
    encoder_ = Ort::Session(env_, encoder.data(), encoder.size(), options);
    Ort::AllocatorWithDefaultOptions allocator;
    input_name_ = segmentation_.GetInputNameAllocated(0, allocator).get();
    output_name_ = segmentation_.GetOutputNameAllocated(0, allocator).get();
  }

  void Cancel() noexcept { cancellation_->Cancel(); }
  bool IsCancelled() const noexcept { return cancellation_->IsCancelled(); }

  Window Process(std::vector<float>& pcm, int64_t window_start_sample = 0,
                 bool cache_fbank = false) {
    community::CheckCancellation(cancellation_->token());
    if (pcm.size() != 160000) throw std::runtime_error("Community requires a 10 second window");
    std::lock_guard<std::mutex> lock(inference_mutex_);
    community::CheckCancellation(cancellation_->token());
    // Keep the thread that drives the encoder pool on the requested CPUs too.
    ScopedCommunityScheduling scope(scheduling_);
    Window result;
    auto start = Clock::now();
    auto memory = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    std::array<int64_t, 3> shape{1, 1, 160000};
    auto tensor = Ort::Value::CreateTensor<float>(memory, pcm.data(), pcm.size(), shape.data(), 3);
    const char* input_names[] = {input_name_.c_str()};
    const char* output_names[] = {output_name_.c_str()};
    auto output = RunCommunityOrt(cancellation_, [&](const Ort::RunOptions& options) {
      return segmentation_.Run(options, input_names, &tensor, 1, output_names, 1);
    });
    community::CheckCancellation(cancellation_->token());
    if (output[0].GetTensorTypeAndShapeInfo().GetElementCount() != 589 * 7) {
      throw std::runtime_error("invalid Community segmentation output");
    }
    const auto* logits = output[0].GetTensorData<float>();
    result.segments.resize(589 * 3);
    std::vector<float> masks(3 * 589), clean(3 * 589);
    int clean_count[3] = {};
    constexpr int codes[7] = {0, 1, 2, 4, 3, 5, 6};
    for (int frame = 0; frame < 589; ++frame) {
      community::CheckCancellation(cancellation_->token());
      int label = std::max_element(logits + frame * 7, logits + (frame + 1) * 7) - (logits + frame * 7);
      int bits = codes[label];
      for (int channel = 0; channel < 3; ++channel) {
        float active = (bits & (1 << channel)) ? 1.f : 0.f;
        result.segments[frame * 3 + channel] = masks[channel * 589 + frame] = active;
        clean[channel * 589 + frame] = (bits & (bits - 1)) == 0 ? active : 0.f;
        clean_count[channel] += clean[channel * 589 + frame];
      }
    }
    for (int channel = 0; channel < 3; ++channel) {
      if (clean_count[channel] > 2) std::copy(clean.begin() + channel * 589,
        clean.begin() + (channel + 1) * 589, masks.begin() + channel * 589);
    }
    result.segmentation_ms = Milliseconds(start);
    start = Clock::now();
    auto features = community::Fbank(pcm, constants_, cancellation_->token(),
                                     cache_fbank ? &fbank_cache_ : nullptr,
                                     window_start_sample);
    result.feature_ms = Milliseconds(start);
    std::array<int64_t, 3> feature_shape{1, 998, 80}, mask_shape{1, 3, 589};
    std::array<int64_t, 3> encoded_shape{1, 2560, 125};
    auto feature_tensor = Ort::Value::CreateTensor<float>(memory, features.data(), features.size(), feature_shape.data(), 3);
    const char* encoder_inputs[] = {"fbank"};
    const char* encoder_outputs[] = {"/resnet/pool/Reshape_output_0"};
    start = Clock::now();
    // The split graphs retain the pinned model's weights. Encoded features
    // belong to this Process call and outlive all of its synchronous pooling
    // calls; they are never retained across windows, generations or sessions.
    auto encoded = RunCommunityOrt(cancellation_, [&](const Ort::RunOptions& options) {
      return encoder_.Run(options, encoder_inputs, &feature_tensor, 1, encoder_outputs, 1);
    });
    community::CheckCancellation(cancellation_->token());
    if (encoded[0].GetTensorTypeAndShapeInfo().GetElementCount() != 2560 * 125) {
      throw std::runtime_error("invalid Community encoder output");
    }
    auto* encoded_values = encoded[0].GetTensorMutableData<float>();
    std::vector<Ort::Value> tensors;
    tensors.push_back(Ort::Value::CreateTensor<float>(memory, encoded_values, 2560 * 125, encoded_shape.data(), 3));
    tensors.push_back(Ort::Value::CreateTensor<float>(memory, masks.data(), masks.size(), mask_shape.data(), 3));
    const char* names[] = {"/resnet/pool/Reshape_output_0", "masks"};
    const char* outputs[] = {"embeddings"};
    auto embeddings = RunCommunityOrt(cancellation_, [&](const Ort::RunOptions& options) {
      return pooling_.Run(options, names, tensors.data(), 2, outputs, 1);
    });
    community::CheckCancellation(cancellation_->token());
    if (embeddings[0].GetTensorTypeAndShapeInfo().GetElementCount() != 3 * 256) {
      throw std::runtime_error("invalid Community embedding output");
    }
    const auto* values = embeddings[0].GetTensorData<float>();
    result.embeddings.assign(values, values + 3 * 256);
    // Keep the full-window vectors above for compatibility, and also export
    // one embedding per disconnected clean run. Overlap runs are exported as
    // non-trainable sentinels so they cannot fall back to a mixed identity.
    struct PendingRun {
      size_t output_offset;
      int channel;
      int begin;
      int end;
    };
    std::vector<PendingRun> pending_runs;
    std::vector<float> packed_run_masks;
    auto flush_pending_runs = [&]() {
      if (pending_runs.empty()) return;
      community::CheckCancellation(cancellation_->token());
      if (packed_run_masks.empty()) packed_run_masks.resize(3 * 589, 0.f);
      std::fill(packed_run_masks.begin(), packed_run_masks.end(), 0.f);
      for (size_t slot = 0; slot < pending_runs.size(); ++slot) {
        const auto& pending = pending_runs[slot];
        for (int frame = pending.begin; frame < pending.end; ++frame) {
          packed_run_masks[slot * 589 + frame] = 1.f;
        }
      }
      std::vector<Ort::Value> run_tensors;
      run_tensors.reserve(2);
      run_tensors.push_back(Ort::Value::CreateTensor<float>(memory, encoded_values,
        2560 * 125, encoded_shape.data(), 3));
      run_tensors.push_back(Ort::Value::CreateTensor<float>(memory, packed_run_masks.data(),
        packed_run_masks.size(), mask_shape.data(), 3));
      community::CheckCancellation(cancellation_->token());
      auto run_output = RunCommunityOrt(cancellation_, [&](const Ort::RunOptions& options) {
        return pooling_.Run(options, names, run_tensors.data(), 2, outputs, 1);
      });
      community::CheckCancellation(cancellation_->token());
      if (run_output[0].GetTensorTypeAndShapeInfo().GetElementCount() != 3 * 256) {
        throw std::runtime_error("invalid Community run embedding output");
      }
      const auto* run_values = run_output[0].GetTensorData<float>();
      community::CheckCancellation(cancellation_->token());
      for (size_t slot = 0; slot < pending_runs.size(); ++slot) {
        const auto& pending = pending_runs[slot];
        std::copy(run_values + slot * 256, run_values + (slot + 1) * 256,
                  result.run_embeddings.begin() + pending.output_offset);
      }
      community::CheckCancellation(cancellation_->token());
      pending_runs.clear();
    };
    for (int channel = 0; channel < 3; ++channel) {
      const int base = channel * 589;
      int begin = -1;
      int kind = -1; // 1 = clean, 0 = overlap/blocked, -1 = inactive.
      for (int frame = 0; frame <= 589; ++frame) {
        community::CheckCancellation(cancellation_->token());
        const bool active = frame < 589 && masks[base + frame] > 0;
        const int next_kind = active ? (clean[base + frame] > 0 ? 1 : 0) : -1;
        if (next_kind != kind && begin >= 0) {
          const int end = frame;
          // Match the same frame-center cells used for public reconstruction.
          // Other runs, pauses and overlap must not set this run's level.
          double squared = 0;
          const size_t first = std::min(pcm.size(), static_cast<size_t>(std::llround(495.5 + begin * 270.)));
          const size_t last = std::min(pcm.size(), static_cast<size_t>(std::llround(495.5 + end * 270.)));
          if (kind == 1) for (size_t i = first; i < last; ++i) squared += static_cast<double>(pcm[i]) * pcm[i];
          result.run_rms.push_back(kind == 1 && last > first ? std::sqrt(squared / (last - first)) : 0.f);
          if (kind == 1 && end - begin >= .2 * 589) {
            // The pinned model pools each mask channel independently. When
            // this run is the entire selected channel mask, its vector was
            // already computed from these exact features in this window.
            // A disconnected tail (including a short one) prevents reuse.
            const int selected_frames = std::count(masks.begin() + base,
              masks.begin() + base + 589, 1.f);
            if (selected_frames == end - begin) {
              result.run_embeddings.insert(result.run_embeddings.end(), values + channel * 256,
                                           values + (channel + 1) * 256);
            } else {
              const size_t output_offset = result.run_embeddings.size();
              result.run_embeddings.insert(result.run_embeddings.end(), 256, 0.f);
              pending_runs.push_back({output_offset, channel, begin, end});
              if (pending_runs.size() == 3) flush_pending_runs();
            }
          } else if (kind == 0) {
            // A finite zero vector would become eligible for a long overlap
            // run. NaN is deliberately rejected by the clusterer and keeps
            // the overlap anonymous without inventing a speaker identity.
            result.run_embeddings.insert(result.run_embeddings.end(), 256,
                                         std::numeric_limits<float>::quiet_NaN());
          } else {
            result.run_embeddings.insert(result.run_embeddings.end(), 256, 0.f);
          }
          result.run_ranges.push_back(0);
          result.run_ranges.push_back(channel);
          result.run_ranges.push_back(begin);
          result.run_ranges.push_back(end);
          begin = -1;
        }
        if (next_kind >= 0 && begin < 0) begin = frame;
        kind = next_kind;
      }
    }
    flush_pending_runs();
    result.embedding_ms = Milliseconds(start);
    return result;
  }

  std::string Cluster(const std::vector<float>& segments, const std::vector<float>& embeddings,
                      const std::vector<float>& run_embeddings, const std::vector<float>& run_ranges,
                      int max_speakers, const std::vector<double>& starts, double begin_sample,
                      const std::vector<float>& run_rms = {},
                      bool include_frame_hard = true) const {
    community::CheckCancellation(cancellation_->token());
#if defined(__OHOS__)
    // Cluster reads immutable PLDA and owns its work buffers. Cancellation and
    // scheduling reports have their own locks; ORT and fbank stay in Process.
    std::lock_guard<std::mutex> lock(cluster_mutex_);
#else
    std::lock_guard<std::mutex> lock(inference_mutex_);
#endif
    community::CheckCancellation(cancellation_->token());
    if (segments.empty() || segments.size() % (589 * 3) || max_speakers < 1 || max_speakers > 4) {
      throw std::runtime_error("invalid Community clustering input");
    }
    ScopedCommunityScheduling scope(scheduling_);
    int windows = segments.size() / (589 * 3);
    std::vector<int32_t> native_ranges;
    native_ranges.reserve(run_ranges.size());
    for (float value : run_ranges) {
      community::CheckCancellation(cancellation_->token());
      if (!std::isfinite(value) || value != std::floor(value)) {
        throw std::runtime_error("invalid Community run range");
      }
      native_ranges.push_back(static_cast<int32_t>(value));
    }
    auto result = community::Cluster(segments, embeddings, windows, plda_, max_speakers,
                                     run_embeddings, native_ranges, run_rms,
                                     cancellation_->token());
    community::CheckCancellation(cancellation_->token());
    auto turns = community::Reconstruct(segments, result.hard, starts, begin_sample, max_speakers,
                                        result.frame_hard, cancellation_->token());
    community::CheckCancellation(cancellation_->token());
    std::ostringstream json;
    json << std::setprecision(17) << "{\"speakerCount\":" << result.centroids.size();
    auto ints = [&](const char* key, const std::vector<int>& values) {
      json << ",\"" << key << "\":[";
      for (size_t i = 0; i < values.size(); ++i) { if (i) json << ','; json << values[i]; }
      json << ']';
    };
    ints("hard", result.hard);
    // The per-frame label grid is 589 * 3 integers per window and therefore
    // grows with the whole session (about 1.57 M integers at 15 minutes). Only
    // the diagnostic build consumes it, so a caller that records no diagnostics
    // must not pay to build and parse it. `Reconstruct` above already consumed
    // the in-memory grid, so reconstruction is unaffected either way.
    if (include_frame_hard) ints("frameHard", result.frame_hard);
    ints("trainingIndices", result.trainingIndices);
    ints("trainingRunIndices", result.trainingRunIndices);
    ints("ahc", result.ahc);
    ints("retainedClusters", result.retainedClusters);
    auto matrix = [&](const char* key, const community::Matrix& rows) {
      json << ",\"" << key << "\":[";
      for (size_t i = 0; i < rows.size(); ++i) {
        if (i) json << ',';
        json << '[';
        for (size_t j = 0; j < rows[i].size(); ++j) {
          if (j) json << ',';
          if (std::isfinite(rows[i][j])) json << rows[i][j];
          else json << "null";
        }
        json << ']';
      }
      json << ']';
    };
    matrix("scores", result.scores);
    matrix("centroids", result.centroids);
    matrix("posteriors", result.vbx.q);
    json << ",\"capacityRms\":[";
    for (size_t i = 0; i < result.capacityRms.size(); ++i) { if (i) json << ','; json << result.capacityRms[i]; }
    json << ']';
    json << ",\"usedKMeans\":" << (result.usedKMeans ? "true" : "false")
         << ",\"usedAhcFallback\":" << (result.usedAhcFallback ? "true" : "false")
         << ",\"shortRunTrainingCount\":" << result.shortRunTrainingCount;
    json << ",\"priors\":[";
    for (size_t i = 0; i < result.vbx.priors.size(); ++i) { if (i) json << ','; json << result.vbx.priors[i]; }
    json << "],\"turns\":[";
    for (size_t i = 0; i < turns.size(); ++i) {
      if (i) json << ',';
      json << '[' << turns[i].begin * 1000 << ',' << turns[i].end * 1000 << ',' << turns[i].speaker << ']';
    }
    json << "]}";
    return json.str();
  }

 private:
  std::shared_ptr<CommunityCancellation> cancellation_ = std::make_shared<CommunityCancellation>();
  Ort::Env env_;
  // Declared before the sessions on purpose: ORT joins its custom worker threads
  // while a session is destroyed, and each worker's scope reports through this
  // policy on the way out. Reverse member destruction must reach the sessions
  // first, or those joins would touch a destroyed policy.
  CommunityScheduling scheduling_;
  Ort::Session segmentation_{nullptr}, encoder_{nullptr}, pooling_{nullptr};
  std::string input_name_, output_name_;
  std::vector<float> constants_;
  community::FbankCache fbank_cache_;
  community::Plda plda_;
  mutable std::mutex inference_mutex_;
#if defined(__OHOS__)
  mutable std::mutex cluster_mutex_;
#endif
};

#ifndef __ANDROID__
// Each session owns its handle. Async calls keep a shared reference after close;
// the ArkTS client also keeps its Runtime lease until all calls have settled.
std::mutex model_mutex;
std::unordered_map<uint32_t, std::shared_ptr<Model>> models;
uint32_t next_handle = 1;
enum class Operation { Load, Process, Cluster };
struct Work {
  Operation operation;
  napi_async_work work = nullptr;
  napi_deferred deferred = nullptr;
  std::shared_ptr<Model> model;
  // Keep the resource provider alive across the native worker. Unlike ArkTS
  // model arrays, these bytes are released with Work rather than by later GC.
  napi_env resource_env = nullptr;
  napi_ref resource_ref = nullptr;
  std::unique_ptr<NativeResourceManager, decltype(&OH_ResourceManager_ReleaseNativeResourceManager)>
    resource_manager{nullptr, OH_ResourceManager_ReleaseNativeResourceManager};
  std::array<std::vector<uint8_t>, 5> assets;
  std::vector<float> pcm, segments, embeddings, run_embeddings;
  std::vector<float> run_ranges, run_rms;
  std::vector<double> window_starts;
  double begin_sample = 0;
  int64_t window_start_sample = 0;
  bool cache_fbank = false;
  Window window;
  int max_speakers = 4;
  int encoder_threads = kDefaultEncoderThreads;
  CommunityScheduling scheduling;
  bool include_frame_hard = true;
  std::string result, error;
  ~Work() {
    resource_manager.reset();
    if (resource_ref) napi_delete_reference(resource_env, resource_ref);
  }
};
void Execute(napi_env, void* data) {
  auto& task = *static_cast<Work*>(data);
  try {
    if (task.operation == Operation::Load) {
      if (task.resource_manager) {
        constexpr const char* names[] = {
          "amphion-dingqiao/pyannote-segmentation-3.0.onnx",
          "amphion-dingqiao/community-wespeaker-encoder.int8.onnx",
          "amphion-dingqiao/community-wespeaker-pool.fp32.onnx",
          "amphion-dingqiao/community-feature.f32", "amphion-dingqiao/community-plda.f64"
        };
        for (size_t i = 0; i < task.assets.size(); ++i) {
          task.assets[i] = ReadCommunityAsset(task.resource_manager.get(), names[i]);
        }
      }
      task.model = std::make_shared<Model>(task.assets[0], task.assets[1], task.assets[2],
                                           task.assets[3], task.assets[4], task.encoder_threads,
                                           task.scheduling);
    } else if (task.operation == Operation::Process) {
      if (task.model->IsCancelled()) throw std::runtime_error("Community operation cancelled");
      task.window = task.model->Process(task.pcm, task.window_start_sample, task.cache_fbank);
    } else {
      if (task.model->IsCancelled()) throw std::runtime_error("Community operation cancelled");
      task.result = task.model->Cluster(task.segments, task.embeddings, task.run_embeddings,
                                        task.run_ranges, task.max_speakers, task.window_starts,
                                        task.begin_sample, task.run_rms, task.include_frame_hard);
    }
  } catch (const std::exception& error) {
    task.error = task.model && task.model->IsCancelled()
      ? "Community operation cancelled" : error.what();
  }
}
// Optional trailing scheduling request. An absent argument means "no request",
// which must stay distinct from a present but empty string.
std::string OptionalString(napi_env env, napi_value value, const char* what) {
  if (value == nullptr) return std::string();
  size_t length = 0;
  if (napi_get_value_string_utf8(env, value, nullptr, 0, &length) != napi_ok) {
    throw std::runtime_error(what);
  }
  std::string text(length + 1, '\0');
  size_t written = 0;
  if (napi_get_value_string_utf8(env, value, text.data(), text.size(), &written) != napi_ok) {
    throw std::runtime_error(what);
  }
  text.resize(written);
  return text;
}
void FloatProperty(napi_env env, napi_value object, const char* name, const std::vector<float>& values) {  napi_value buffer, array;
  void* bytes = nullptr;
  napi_create_arraybuffer(env, values.size() * sizeof(float), &bytes, &buffer);
  if (!values.empty()) std::memcpy(bytes, values.data(), values.size() * sizeof(float));
  napi_create_typedarray(env, napi_float32_array, values.size(), buffer, 0, &array);
  napi_set_named_property(env, object, name, array);
}
void NumberProperty(napi_env env, napi_value object, const char* name, double value) {
  napi_value number;
  napi_create_double(env, value, &number);
  napi_set_named_property(env, object, name, number);
}
void Complete(napi_env env, napi_status status, void* data) {
  std::unique_ptr<Work> task(static_cast<Work*>(data));
  if (task->model && task->model->IsCancelled() && task->error.empty()) {
    task->error = "Community operation cancelled";
  }
  if (status != napi_ok && task->error.empty()) task->error = "Community operation cancelled";
  napi_value value = nullptr;
  if (!task->error.empty()) {
    napi_value message;
    napi_create_string_utf8(env, task->error.c_str(), NAPI_AUTO_LENGTH, &message);
    napi_create_error(env, nullptr, message, &value);
    napi_reject_deferred(env, task->deferred, value);
  } else {
    if (task->operation == Operation::Load) {
      std::lock_guard<std::mutex> lock(model_mutex);
      uint32_t handle = next_handle++;
      models.emplace(handle, std::move(task->model));
      napi_create_uint32(env, handle, &value);
    } else if (task->operation == Operation::Process) {
      napi_create_object(env, &value);
      FloatProperty(env, value, "segments", task->window.segments);
      FloatProperty(env, value, "embeddings", task->window.embeddings);
      FloatProperty(env, value, "runEmbeddings", task->window.run_embeddings);
      FloatProperty(env, value, "runRanges", task->window.run_ranges);
      FloatProperty(env, value, "runRms", task->window.run_rms);
      NumberProperty(env, value, "segmentationMs", task->window.segmentation_ms);
      NumberProperty(env, value, "featureMs", task->window.feature_ms);
      NumberProperty(env, value, "embeddingMs", task->window.embedding_ms);
    } else napi_create_string_utf8(env, task->result.c_str(), task->result.size(), &value);
    napi_resolve_deferred(env, task->deferred, value);
  }
  napi_delete_async_work(env, task->work);
}
napi_value Queue(napi_env env, napi_callback_info info, Operation operation, bool from_resources = false) {
  size_t count = 10;
  napi_value args[10] = {};
  napi_get_cb_info(env, info, &count, args, nullptr, nullptr);
  try {
    const bool legacyCluster = operation == Operation::Cluster && count == 6;
    const bool clusterLevels = operation == Operation::Cluster && (count == 9 || count == 10);
    bool accepted = false;
    if (operation == Operation::Cluster) {
      accepted = legacyCluster || count == 8 || clusterLevels;
    } else if (operation == Operation::Process) {
      accepted = count == 2 || count == 3 || count == 4;
    } else if (from_resources) {
      accepted = count == 1 || count == 2 || count == 3;
    } else {
      accepted = count == 5 || count == 6 || count == 7;
    }
    if (!accepted) throw std::runtime_error("invalid Community arguments");
    auto task = std::make_unique<Work>();
    task->operation = operation;
    if (operation == Operation::Load) {
      if (from_resources) {
        task->resource_manager.reset(OH_ResourceManager_InitNativeResourceManager(env, args[0]));
        if (!task->resource_manager) throw std::runtime_error("invalid Community resource manager");
        task->resource_env = env;
        if (napi_create_reference(env, args[0], 1, &task->resource_ref) != napi_ok) {
          throw std::runtime_error("Community resource reference failed");
        }
        // The budget and the scheduling request travel in the same call, so each
        // present argument is parsed on its own instead of being tied to one
        // exact argument count. Tying threads to count==2 silently discarded the
        // caller's budget as soon as a scheduling string was appended.
        if (count >= 2 && napi_get_value_int32(env, args[1], &task->encoder_threads) != napi_ok) {
          throw std::runtime_error("invalid Community encoder threads");
        }
        if (count == 3) {
          ParseCommunityScheduling(OptionalString(env, args[2], "invalid Community scheduling option"),
                                   &task->scheduling);
        }
      } else {
        for (size_t i = 0; i < task->assets.size(); ++i) task->assets[i] = CopyArray<uint8_t>(env, args[i], napi_uint8_array);
        if (count >= 6 && napi_get_value_int32(env, args[5], &task->encoder_threads) != napi_ok) {
          throw std::runtime_error("invalid Community encoder threads");
        }
        if (count == 7) {
          ParseCommunityScheduling(OptionalString(env, args[6], "invalid Community scheduling option"),
                                   &task->scheduling);
        }
      }
    } else {
      uint32_t handle = 0;
      if (napi_get_value_uint32(env, args[0], &handle) != napi_ok) throw std::runtime_error("invalid Community handle");
      {
        std::lock_guard<std::mutex> lock(model_mutex);
        auto found = models.find(handle);
        if (found == models.end()) throw std::runtime_error("Community model is closed");
        task->model = found->second;
      }
      if (operation == Operation::Process) {
        task->pcm = CopyArray<float>(env, args[1], napi_float32_array);
        if (count >= 3) {
          double start = 0;
          if (napi_get_value_double(env, args[2], &start) != napi_ok ||
              !std::isfinite(start) || start < 0 || start != std::floor(start) ||
              start > static_cast<double>(std::numeric_limits<int64_t>::max())) {
            throw std::runtime_error("invalid Community window start sample");
          }
          task->window_start_sample = static_cast<int64_t>(start);
          task->cache_fbank = true;
          if (count == 4 && napi_get_value_bool(env, args[3], &task->cache_fbank) != napi_ok) {
            throw std::runtime_error("invalid Community fbank cache option");
          }
        }
      } else {
        task->segments = CopyArray<float>(env, args[1], napi_float32_array);
        task->embeddings = CopyArray<float>(env, args[2], napi_float32_array);
        size_t offset = 0;
        if (!legacyCluster) {
          task->run_embeddings = CopyArray<float>(env, args[3], napi_float32_array);
          task->run_ranges = CopyArray<float>(env, args[4], napi_float32_array);
          offset = 2;
          if (clusterLevels) {
            task->run_rms = CopyArray<float>(env, args[8], napi_float32_array);
            if (count == 10 &&
                napi_get_value_bool(env, args[9], &task->include_frame_hard) != napi_ok) {
              throw std::runtime_error("invalid Community frame-hard option");
            }
          }
        }
        if (napi_get_value_int32(env, args[3 + offset], &task->max_speakers) != napi_ok) throw std::runtime_error("invalid speaker cap");
        task->window_starts = CopyArray<double>(env, args[4 + offset], napi_float64_array);
        if (napi_get_value_double(env, args[5 + offset], &task->begin_sample) != napi_ok) throw std::runtime_error("invalid reconstruction boundary");
      }
    }
    napi_value promise, name;
    if (napi_create_promise(env, &task->deferred, &promise) != napi_ok) throw std::runtime_error("Community promise failed");
    napi_create_string_utf8(env, "AmphionCommunityDiarization", NAPI_AUTO_LENGTH, &name);
    auto status = napi_create_async_work(env, nullptr, name, Execute, Complete, task.get(), &task->work);
    if (status == napi_ok) status = napi_queue_async_work(env, task->work);
    if (status != napi_ok) {
      if (task->work) napi_delete_async_work(env, task->work);
      napi_value message;
      napi_create_string_utf8(env, "Community work queue failed", NAPI_AUTO_LENGTH, &message);
      napi_reject_deferred(env, task->deferred, message);
    } else task.release();
    return promise;
  } catch (const std::exception& error) { napi_throw_error(env, nullptr, error.what()); return nullptr; }
}
napi_value Load(napi_env env, napi_callback_info info) { return Queue(env, info, Operation::Load); }
napi_value LoadResources(napi_env env, napi_callback_info info) { return Queue(env, info, Operation::Load, true); }
napi_value Process(napi_env env, napi_callback_info info) { return Queue(env, info, Operation::Process); }
napi_value Cluster(napi_env env, napi_callback_info info) { return Queue(env, info, Operation::Cluster); }
napi_value Cancel(napi_env env, napi_callback_info info) {
  size_t count = 1;
  napi_value arg = nullptr, result = nullptr;
  napi_get_cb_info(env, info, &count, &arg, nullptr, nullptr);
  uint32_t handle = 0;
  std::shared_ptr<Model> model;
  if (count == 1 && napi_get_value_uint32(env, arg, &handle) == napi_ok) {
    std::lock_guard<std::mutex> lock(model_mutex);
    auto found = models.find(handle);
    if (found != models.end()) model = found->second;
  }
  if (model) model->Cancel();
  napi_get_undefined(env, &result);
  return result;
}

napi_value Close(napi_env env, napi_callback_info info) {
  size_t count = 1;
  napi_value arg = nullptr, result = nullptr;
  napi_get_cb_info(env, info, &count, &arg, nullptr, nullptr);
  uint32_t handle = 0;
  if (count == 1 && napi_get_value_uint32(env, arg, &handle) == napi_ok) {
    std::lock_guard<std::mutex> lock(model_mutex);
    models.erase(handle);
  }
  napi_get_undefined(env, &result);
  return result;
}
}  // namespace

void RegisterCommunityDiarization(napi_env env, napi_value exports) {
  napi_property_descriptor methods[] = {
    {"loadCommunityDiarization", nullptr, Load, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"loadCommunityDiarizationResources", nullptr, LoadResources, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"normalizeCommunityPcm16Window", nullptr, NormalizeCommunityPcm16Window, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"processCommunityDiarization", nullptr, Process, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"clusterCommunityDiarization", nullptr, Cluster, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"cancelCommunityDiarization", nullptr, Cancel, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"closeCommunityDiarization", nullptr, Close, nullptr, nullptr, nullptr, napi_default, nullptr},
  };
  napi_define_properties(env, exports, sizeof(methods) / sizeof(methods[0]), methods);
}

#else
} // namespace
#include "community_diarization_jni.inc"
#endif
