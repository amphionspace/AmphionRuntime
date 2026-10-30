// Sortformer-66M-4spk streaming speaker diarization for the Harmony SDK.
//
// One session owns one engine. PCM arrives in order; the engine keeps a
// streaming log-mel front end, cuts 9.92 s chunks (124 encoder frames), runs
// pre_encode -> encoder_layers -> speaker_head over [speaker cache | FIFO |
// chunk | right context], commits the speaker-cache state machine, and reports
// per-slot speech runs at 10 ms. Before each chunk completes it can run one
// preview pass over the chunk's first `preview_frames` mel frames against the
// current cache without advancing it, which is what a 5 s role refresh shows a
// caller ahead of the chunk's final result.
//
// The four slots are the model's own arrival-ordered speaker identities and
// stay stable for the session; nothing here clusters or re-labels. Spec:
// delivery README §2-§4 and runtime_config.json (chunk_len 124, spkcache 188,
// fifo 188, right context 1, scores_boost_latest 0). Numerics match the
// whole-file reference pipeline frame for frame: the front end sees real
// samples on both sides of every frame, zero padding only at session start
// and at flush, exactly as the reference pads.
#include "onnxruntime_cxx_api.h"

#include <hilog/log.h>
#include <node_api.h>
#include <qos/qos.h>
#include <rawfile/raw_file_manager.h>
#include <sys/resource.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <complex>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <deque>
#include <functional>
#include <future>
#include <limits>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

namespace {

constexpr int kMel = 128, kFft = 512, kWin = 400, kHop = 160, kBins = kFft / 2 + 1;
constexpr int kSub = 8, kSpk = 4, kDim = 512;
constexpr int kSpkCache = 188, kChunk = 124, kFifo = 188, kRightCtx = 1;
constexpr int kMelPerChunk = kChunk * kSub;        // 992 mel frames = 9.92 s
constexpr int kRightCtxMel = kRightCtx * kSub;     // 8 mel frames = 80 ms
constexpr int kMelLookahead = kFft / 2;            // 256 samples: a frame's right half
constexpr double kPreemph = 0.97;
constexpr double kLogGuard = 5.9604644775390625e-08;  // 2^-24
constexpr float kActiveThreshold = 0.5f;
constexpr unsigned kLogDomain = 0x6666;
constexpr const char* kLogTag = "AmphionScheduling";
constexpr const char* kAssetDir = "amphion-dingqiao/sortformer-66M-4spk/";

using Clock = std::chrono::steady_clock;
double Ms(Clock::time_point start) {
  return std::chrono::duration<double, std::milli>(Clock::now() - start).count();
}

// ------------------------------------------------------------ assets --------

std::vector<uint8_t> ReadAsset(NativeResourceManager* manager, const std::string& name) {
  std::unique_ptr<RawFile, decltype(&OH_ResourceManager_CloseRawFile)> file(
    OH_ResourceManager_OpenRawFile(manager, name.c_str()), OH_ResourceManager_CloseRawFile);
  if (!file) throw std::runtime_error("Sortformer model asset unavailable: " + name);
  const long size = OH_ResourceManager_GetRawFileSize(file.get());
  if (size <= 0) throw std::runtime_error("Sortformer model asset is empty: " + name);
  std::vector<uint8_t> bytes(static_cast<size_t>(size));
  size_t offset = 0;
  while (offset < bytes.size()) {
    const size_t remaining = bytes.size() - offset;
    const int read = OH_ResourceManager_ReadRawFile(file.get(), bytes.data() + offset,
      std::min(remaining, static_cast<size_t>(std::numeric_limits<int>::max())));
    if (read <= 0 || static_cast<size_t>(read) > remaining) {
      throw std::runtime_error("Sortformer model asset read failed: " + name);
    }
    offset += static_cast<size_t>(read);
  }
  return bytes;
}

// Minimal .npy reader for the delivered float32 tables (v1/v2 header, C order).
std::vector<float> ParseNpyFloat32(const std::vector<uint8_t>& bytes, size_t expected, const char* what) {
  if (bytes.size() < 12 || std::memcmp(bytes.data(), "\x93NUMPY", 6) != 0) {
    throw std::runtime_error(std::string("Sortformer table is not npy: ") + what);
  }
  const int major = bytes[6];
  size_t header_len, header_start;
  if (major == 1) { header_len = bytes[8] | (bytes[9] << 8); header_start = 10; }
  else {
    header_len = bytes[8] | (bytes[9] << 8) | (bytes[10] << 16) | (static_cast<size_t>(bytes[11]) << 24);
    header_start = 12;
  }
  if (header_start + header_len > bytes.size()) throw std::runtime_error(std::string("truncated npy: ") + what);
  const std::string header(reinterpret_cast<const char*>(bytes.data()) + header_start, header_len);
  if (header.find("'<f4'") == std::string::npos || header.find("'fortran_order': True") != std::string::npos) {
    throw std::runtime_error(std::string("Sortformer table must be C-order float32: ") + what);
  }
  const size_t payload = bytes.size() - header_start - header_len;
  if (payload != expected * sizeof(float)) {
    throw std::runtime_error(std::string("Sortformer table size mismatch: ") + what);
  }
  std::vector<float> out(expected);
  std::memcpy(out.data(), bytes.data() + header_start + header_len, payload);
  return out;
}

// -------------------------------------------------------- role worker -------
// The same owned worker the Community chain used: role work runs behind the
// recognizer (nice 10) and, where the system honours it, at a requested QoS.

int RoleQos(const std::string& recognizer_qos) {
  if (recognizer_qos == "default") return -1;
  if (recognizer_qos == "user-initiated") return QOS_DEFAULT;
  if (recognizer_qos == "user-interactive") return QOS_USER_INITIATED;
  throw std::runtime_error("invalid Sortformer recognizer QoS");
}

int RoleQosOverride(const std::string& role_qos, int inherited) {
  if (role_qos.empty() || role_qos == "inherit") return inherited;
  if (role_qos == "background") return QOS_BACKGROUND;
  if (role_qos == "utility") return QOS_UTILITY;
  if (role_qos == "default") return QOS_DEFAULT;
  throw std::runtime_error("invalid Sortformer role QoS");
}

class RoleWorker {
 public:
  explicit RoleWorker(int qos = -1) : qos_(qos) { thread_ = std::thread([this] { Loop(); }); }
  ~RoleWorker() {
    { std::lock_guard<std::mutex> lock(mutex_); stopping_ = true; }
    ready_.notify_one();
    thread_.join();
  }
  RoleWorker(const RoleWorker&) = delete;
  RoleWorker& operator=(const RoleWorker&) = delete;

  std::future<void> Post(std::function<void()> task) {
    std::packaged_task<void()> packaged(std::move(task));
    auto future = packaged.get_future();
    { std::lock_guard<std::mutex> lock(mutex_); tasks_.push_back(std::move(packaged)); }
    ready_.notify_one();
    return future;
  }

 private:
  static constexpr int kRoleNice = 10;
  void Loop() {
    setpriority(PRIO_PROCESS, static_cast<id_t>(gettid()), kRoleNice);
    if (qos_ >= 0) {
      const int result = OH_QoS_SetThreadQoS(static_cast<QoS_Level>(qos_));
      QoS_Level effective = QOS_DEFAULT;
      const bool read = result == 0 && OH_QoS_GetThreadQoS(&effective) == 0;
      OH_LOG_Print(LOG_APP, LOG_INFO, kLogDomain, kLogTag,
                   "sortformer role-qos requested=%{public}d result=%{public}d effective=%{public}d",
                   qos_, result, read ? static_cast<int>(effective) : -1);
    }
    for (;;) {
      std::packaged_task<void()> task;
      {
        std::unique_lock<std::mutex> lock(mutex_);
        ready_.wait(lock, [this] { return stopping_ || !tasks_.empty(); });
        if (tasks_.empty()) return;
        task = std::move(tasks_.front());
        tasks_.pop_front();
      }
      task();
    }
  }
  const int qos_;
  std::mutex mutex_;
  std::condition_variable ready_;
  std::deque<std::packaged_task<void()>> tasks_;
  bool stopping_ = false;
  std::thread thread_;
};

// ----------------------------------------------------- mel front end --------
// NeMo AudioToMelSpectrogramPreprocessor as the delivery instantiates it:
// whole-signal pre-emphasis, hann(400, periodic=False) centred in a 512 frame,
// |X|^2, slaney 128-band filterbank, log(mel + 2^-24), no normalization. Frame
// f covers pre-emphasised samples [f*160-256, f*160+256); the reference pads
// zeros before sample 0 and after the last sample, and so does this stream.
class MelStream {
 public:
  MelStream(std::vector<float> window, std::vector<float> filterbank) {
    window_.assign(kFft, 0.0);
    const int off = (kFft - kWin) / 2;
    for (int i = 0; i < kWin; ++i) window_[off + i] = window[i];
    fb_.assign(filterbank.begin(), filterbank.end());
    first_.resize(kMel);
    end_.resize(kMel);
    for (int m = 0; m < kMel; ++m) {
      int first = 0, end = kBins;
      while (first < end && fb_[m * kBins + first] == 0.0) ++first;
      while (end > first && fb_[m * kBins + end - 1] == 0.0) --end;
      first_[m] = first;
      end_[m] = end;
    }
    bitrev_.resize(kFft);
    for (int i = 0; i < kFft; ++i) {
      int r = 0;
      for (int b = 0; b < 9; ++b) r |= ((i >> b) & 1) << (8 - b);
      bitrev_[i] = r;
    }
    const double pi = std::acos(-1.0);
    twiddle_.resize(kFft / 2);
    for (int k = 0; k < kFft / 2; ++k) twiddle_[k] = std::polar(1.0, -2.0 * pi * k / kFft);
    // Pre-pad: frame 0 starts 256 samples before the first real sample.
    y_.assign(kMelLookahead, 0.0);
    y_base_ = -kMelLookahead;
  }

  // Appends real samples and returns how many new frames became computable.
  int Append(const float* samples, size_t count) {
    for (size_t i = 0; i < count; ++i) {
      y_.push_back(static_cast<double>(samples[i]) - kPreemph * last_);
      last_ = samples[i];
    }
    total_samples_ += static_cast<int64_t>(count);
    return Produce();
  }

  // The stream ends: pad like the reference (zeros, not pre-emphasised) and
  // compute every frame that floor(T / hop) owns.
  int Flush() {
    if (flushed_) return 0;
    flushed_ = true;
    y_.insert(y_.end(), kMelLookahead + kFft, 0.0);
    return Produce(/*flushing=*/true);
  }

  int frames() const { return static_cast<int>(frames_); }
  int64_t samples() const { return total_samples_; }

  // Row-major (frames, 128) for frames [begin, begin + count); begin must not
  // precede the retained window (callers consume in order).
  void Copy(int64_t begin, int count, float* out, int out_stride_frames) const {
    for (int f = 0; f < count; ++f) {
      const float* row = Row(begin + f);
      for (int m = 0; m < kMel; ++m) out[static_cast<size_t>(m) * out_stride_frames + f] = row[m];
    }
  }

  // Frames before `frame` are no longer needed by the chunker.
  void Release(int64_t frame) {
    if (frame <= mel_base_) return;
    const size_t drop = static_cast<size_t>(frame - mel_base_);
    mel_.erase(mel_.begin(), mel_.begin() + std::min(drop * kMel, mel_.size()));
    mel_base_ = frame;
  }

 private:
  const float* Row(int64_t frame) const {
    if (frame < mel_base_ || frame >= frames_) throw std::runtime_error("mel frame out of range");
    return mel_.data() + static_cast<size_t>(frame - mel_base_) * kMel;
  }

  int Produce(bool flushing = false) {
    // Frame f is computable when samples through f*160+256 exist.
    const int64_t limit = flushing ? total_samples_ / kHop : frames_limit_by_samples();
    int produced = 0;
    std::array<std::complex<double>, kFft> a;
    std::array<double, kBins> power;
    while (frames_ < limit) {
      const int64_t start = frames_ * kHop - kMelLookahead;  // absolute sample index
      const size_t offset = static_cast<size_t>(start - y_base_);
      if (offset + kFft > y_.size()) break;
      for (int n = 0; n < kFft; ++n) a[bitrev_[n]] = std::complex<double>(y_[offset + n] * window_[n], 0.0);
      for (int len = 2; len <= kFft; len <<= 1) {
        const int half = len / 2, step = kFft / len;
        for (int i = 0; i < kFft; i += len) {
          for (int j = 0; j < half; ++j) {
            const std::complex<double> v = a[i + j + half] * twiddle_[j * step];
            const std::complex<double> u = a[i + j];
            a[i + j] = u + v;
            a[i + j + half] = u - v;
          }
        }
      }
      for (int k = 0; k < kBins; ++k) power[k] = std::norm(a[k]);
      for (int m = 0; m < kMel; ++m) {
        double mel = 0.0;
        const double* w = fb_.data() + m * kBins;
        for (int k = first_[m]; k < end_[m]; ++k) mel += w[k] * power[k];
        mel_.push_back(static_cast<float>(std::log(mel + kLogGuard)));
      }
      ++frames_;
      ++produced;
    }
    // Keep only what the next frame still needs: from (frames_*160 - 256).
    const int64_t keep_from = frames_ * kHop - kMelLookahead;
    if (keep_from > y_base_) {
      const size_t drop = static_cast<size_t>(keep_from - y_base_);
      y_.erase(y_.begin(), y_.begin() + std::min(drop, y_.size()));
      y_base_ = keep_from;
    }
    return produced;
  }

  int64_t frames_limit_by_samples() const {
    // samples needed for frame f: f*160 + 256 <= total  ->  f <= (total - 256) / 160
    if (total_samples_ < kMelLookahead) return 0;
    return (total_samples_ - kMelLookahead) / kHop + 1;
  }

  std::vector<double> window_, fb_;
  std::vector<int> first_, end_, bitrev_;
  std::vector<std::complex<double>> twiddle_;
  std::deque<double> y_;
  int64_t y_base_ = 0;
  float last_ = 0.f;
  int64_t total_samples_ = 0;
  std::vector<float> mel_;
  int64_t mel_base_ = 0;
  int64_t frames_ = 0;
  bool flushed_ = false;
};

// ------------------------------------------------------------ engine --------

struct Run {  // one contiguous active span of one slot, absolute 10 ms frames
  int64_t begin, end;
};

struct Event {
  bool preview;
  int64_t begin_frame;
  int frames;
  double inference_ms;
  std::array<std::vector<Run>, kSpk> runs;
};

struct State {
  std::vector<float> spkcache = std::vector<float>(kSpkCache * kDim, 0.f);
  std::vector<float> spk_preds = std::vector<float>(kSpkCache * kSpk, 0.f);
  std::vector<float> fifo = std::vector<float>(kFifo * kDim, 0.f);
  int64_t sc_len = 0, f_len = 0, compressed = 0;
};

class Engine {
 public:
  Engine(NativeResourceManager* manager, int threads, int preview_frames)
      : env_(ORT_LOGGING_LEVEL_WARNING, "amphion-sortformer"),
        memory_(Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault)),
        preview_frames_(preview_frames) {
    if (preview_frames_ < 0 || preview_frames_ % kSub != 0 || preview_frames_ >= kMelPerChunk) {
      throw std::runtime_error("Sortformer preview frames must be a multiple of 8 below 992");
    }
    Ort::SessionOptions options;
    options.SetExecutionMode(ExecutionMode::ORT_SEQUENTIAL);
    options.SetInterOpNumThreads(1);
    options.SetIntraOpNumThreads(std::max(1, threads));
    // Bursts of 0.4 s every 9.92 s: spinning workers between them would take
    // from the recognizer, which is the same policy its own sessions follow.
    options.AddConfigEntry("session.force_spinning_stop", "1");
    auto open = [&](const char* name, Ort::Session& into, double& ms) {
      const std::vector<uint8_t> bytes = ReadAsset(manager, std::string(kAssetDir) + name);
      const auto started = Clock::now();
      into = Ort::Session(env_, bytes.data(), bytes.size(), options);
      ms = Ms(started);
    };
    open("pre_encode.ort", pre_, load_ms_[0]);
    open("encoder_layers.int8.ort", enc_, load_ms_[1]);
    open("speaker_head.ort", head_, load_ms_[2]);
    open("spkcache_update.ort", state_, load_ms_[3]);
    sil_ = ParseNpyFloat32(ReadAsset(manager, std::string(kAssetDir) + "learnable_sil_emb.npy"), kDim, "sil_emb");
    mel_ = std::make_unique<MelStream>(
      ParseNpyFloat32(ReadAsset(manager, std::string(kAssetDir) + "mel_window_hann400_periodic_false.npy"), kWin, "window"),
      ParseNpyFloat32(ReadAsset(manager, std::string(kAssetDir) + "mel_filterbank_128x257_slaney.npy"), kMel * kBins, "filterbank"));
    OH_LOG_Print(LOG_APP, LOG_INFO, kLogDomain, kLogTag,
                 "sortformer-load threads=%{public}d previewFrames=%{public}d encoderLoadMs=%{public}.1f",
                 threads, preview_frames_, load_ms_[1]);
  }

  // Feeds samples (or flushes) and returns every event that became final or
  // previewable. Runs on the owned role worker.
  std::vector<Event> Feed(const std::vector<float>& pcm, bool flush) {
    std::vector<Event> events;
    if (finished_) return events;
    if (!pcm.empty()) mel_->Append(pcm.data(), pcm.size());
    if (flush) mel_->Flush();
    Advance(events, flush);
    if (flush) finished_ = true;
    return events;
  }

  int64_t mel_frames() const { return mel_->frames(); }
  int64_t samples() const { return mel_->samples(); }
  const std::array<double, 4>& load_ms() const { return load_ms_; }

 private:
  void Advance(std::vector<Event>& events, bool flushing) {
    for (;;) {
      const int64_t frames = mel_->frames();
      const int64_t avail = frames - chunk_base_;
      if (preview_frames_ > 0 && !preview_done_ && avail >= preview_frames_ + kRightCtxMel) {
        events.push_back(Infer(chunk_base_, preview_frames_ / kSub, kRightCtx, /*commit=*/false));
        preview_done_ = true;
      }
      if (avail >= kMelPerChunk + kRightCtxMel) {
        events.push_back(Infer(chunk_base_, kChunk, kRightCtx, /*commit=*/true));
        chunk_base_ += kMelPerChunk;
        preview_done_ = false;
        mel_->Release(chunk_base_);
        continue;
      }
      break;
    }
    if (flushing) {
      const int64_t avail = mel_->frames() - chunk_base_;
      const int c_len = static_cast<int>(std::min<int64_t>(kChunk, avail / kSub));
      // With fewer than c_len+1 encoder frames left there is no right context;
      // this is exactly the reference's tail rule.
      if (c_len > 0) {
        const int rc = (chunk_base_ + static_cast<int64_t>(c_len + kRightCtx) * kSub <= mel_->frames()) ? kRightCtx : 0;
        events.push_back(Infer(chunk_base_, c_len, rc, /*commit=*/true));
        chunk_base_ += static_cast<int64_t>(c_len) * kSub;
        mel_->Release(chunk_base_);
      }
    }
  }

  std::vector<float> RunSingle(Ort::Session& session, const char* in_name, const char* out_name,
                               std::vector<float>& data, const std::vector<int64_t>& shape,
                               std::vector<int64_t>* out_shape) {
    Ort::Value input = Ort::Value::CreateTensor<float>(memory_, data.data(), data.size(), shape.data(), shape.size());
    std::vector<Ort::Value> outputs = session.Run(Ort::RunOptions{nullptr}, &in_name, &input, 1, &out_name, 1);
    std::vector<int64_t> dims = outputs[0].GetTensorTypeAndShapeInfo().GetShape();
    size_t count = 1;
    for (int64_t d : dims) count *= static_cast<size_t>(d);
    const float* ptr = outputs[0].GetTensorData<float>();
    if (out_shape) *out_shape = dims;
    return std::vector<float>(ptr, ptr + count);
  }

  // One pass over c_len encoder frames from mel frame `base` with rc right
  // context against the current state. commit=true advances the state.
  Event Infer(int64_t base, int c_len, int rc, bool commit) {
    const auto started = Clock::now();
    const int L = (c_len + rc) * kSub;
    std::vector<float> melchunk(static_cast<size_t>(kMel) * L);
    mel_->Copy(base, L, melchunk.data(), L);
    std::vector<int64_t> fshape;
    std::vector<float> feats = RunSingle(pre_, "mel", "feats", melchunk, {1, kMel, L}, &fshape);
    if (fshape.size() != 3 || fshape[1] < c_len + rc || fshape[2] != kDim) {
      throw std::runtime_error("Sortformer pre_encode shape mismatch");
    }
    const int sl = static_cast<int>(st_.sc_len), fl = static_cast<int>(st_.f_len);
    const int ctx_len = sl + fl + c_len + rc;
    std::vector<float> ctx(static_cast<size_t>(ctx_len) * kDim);
    float* dst = ctx.data();
    std::memcpy(dst, st_.spkcache.data(), static_cast<size_t>(sl) * kDim * sizeof(float)); dst += static_cast<size_t>(sl) * kDim;
    std::memcpy(dst, st_.fifo.data(), static_cast<size_t>(fl) * kDim * sizeof(float)); dst += static_cast<size_t>(fl) * kDim;
    std::memcpy(dst, feats.data(), static_cast<size_t>(c_len + rc) * kDim * sizeof(float));
    std::vector<float> enc = RunSingle(enc_, "feats", "enc", ctx, {1, ctx_len, kDim}, nullptr);
    std::vector<int64_t> pshape;
    std::vector<float> probs = RunSingle(head_, "enc", "probs", enc, {1, kDim, ctx_len}, &pshape);
    if (pshape.size() != 3 || pshape[1] != static_cast<int64_t>(ctx_len) * kSub || pshape[2] != kSpk) {
      throw std::runtime_error("Sortformer speaker_head shape mismatch");
    }
    const int s_off = (sl + fl) * kSub;
    Event event;
    event.preview = !commit;
    event.begin_frame = base;
    event.frames = c_len * kSub;
    for (int k = 0; k < kSpk; ++k) {
      int64_t run_begin = -1;
      for (int f = 0; f < event.frames; ++f) {
        const bool active = probs[(static_cast<size_t>(s_off + f)) * kSpk + k] > kActiveThreshold;
        if (active && run_begin < 0) run_begin = base + f;
        if (!active && run_begin >= 0) { event.runs[k].push_back({run_begin, base + f}); run_begin = -1; }
      }
      if (run_begin >= 0) event.runs[k].push_back({run_begin, base + event.frames});
    }
    if (commit) Commit(feats, probs, c_len, ctx_len, sl, fl);
    event.inference_ms = Ms(started);
    return event;
  }

  void Commit(const std::vector<float>& feats, const std::vector<float>& probs, int c_len, int ctx_len,
              int sl, int fl) {
    // Encoder-rate preds: mean of the 8 sub-frames (reduce="mean" in the reference).
    std::vector<float> preds(static_cast<size_t>(ctx_len) * kSpk, 0.f);
    for (int f = 0; f < ctx_len; ++f) {
      for (int k = 0; k < kSpk; ++k) {
        float sum = 0.f;
        for (int j = 0; j < kSub; ++j) sum += probs[(static_cast<size_t>(f) * kSub + j) * kSpk + k];
        preds[static_cast<size_t>(f) * kSpk + k] = sum / kSub;
      }
    }
    std::vector<float> chunk_pad(kChunk * kDim, 0.f), chunk_preds(kChunk * kSpk, 0.f);
    std::vector<float> fifo_preds(kFifo * kSpk, 0.f), cache_preds(kSpkCache * kSpk, 0.f);
    std::memcpy(chunk_pad.data(), feats.data(), static_cast<size_t>(c_len) * kDim * sizeof(float));
    std::memcpy(chunk_preds.data(), preds.data() + static_cast<size_t>(sl + fl) * kSpk, static_cast<size_t>(c_len) * kSpk * sizeof(float));
    std::memcpy(fifo_preds.data(), preds.data() + static_cast<size_t>(sl) * kSpk, static_cast<size_t>(fl) * kSpk * sizeof(float));
    std::memcpy(cache_preds.data(), preds.data(), static_cast<size_t>(sl) * kSpk * sizeof(float));
    int64_t chunk_len = c_len;
    static const char* in_names[] = {"spkcache", "spkcache_preds", "sc_len", "fifo", "f_len", "compressed",
                                     "chunk", "chunk_preds", "chunk_len", "fifo_preds_new", "cache_preds_new", "sil_emb"};
    static const char* out_names[] = {"spkcache_out", "spkcache_preds_out", "sc_len_out",
                                      "fifo_out", "f_len_out", "compressed_out"};
    const int64_t s_cache[] = {1, kSpkCache, kDim}, s_cpreds[] = {1, kSpkCache, kSpk}, s_one[] = {1};
    const int64_t s_fifo[] = {1, kFifo, kDim}, s_fpreds[] = {1, kFifo, kSpk};
    const int64_t s_chunk[] = {1, kChunk, kDim}, s_chpreds[] = {1, kChunk, kSpk}, s_sil[] = {kDim};
    std::vector<Ort::Value> in;
    in.push_back(Ort::Value::CreateTensor<float>(memory_, st_.spkcache.data(), st_.spkcache.size(), s_cache, 3));
    in.push_back(Ort::Value::CreateTensor<float>(memory_, st_.spk_preds.data(), st_.spk_preds.size(), s_cpreds, 3));
    in.push_back(Ort::Value::CreateTensor<int64_t>(memory_, &st_.sc_len, 1, s_one, 1));
    in.push_back(Ort::Value::CreateTensor<float>(memory_, st_.fifo.data(), st_.fifo.size(), s_fifo, 3));
    in.push_back(Ort::Value::CreateTensor<int64_t>(memory_, &st_.f_len, 1, s_one, 1));
    in.push_back(Ort::Value::CreateTensor<int64_t>(memory_, &st_.compressed, 1, s_one, 1));
    in.push_back(Ort::Value::CreateTensor<float>(memory_, chunk_pad.data(), chunk_pad.size(), s_chunk, 3));
    in.push_back(Ort::Value::CreateTensor<float>(memory_, chunk_preds.data(), chunk_preds.size(), s_chpreds, 3));
    in.push_back(Ort::Value::CreateTensor<int64_t>(memory_, &chunk_len, 1, s_one, 1));
    in.push_back(Ort::Value::CreateTensor<float>(memory_, fifo_preds.data(), fifo_preds.size(), s_fpreds, 3));
    in.push_back(Ort::Value::CreateTensor<float>(memory_, cache_preds.data(), cache_preds.size(), s_cpreds, 3));
    in.push_back(Ort::Value::CreateTensor<float>(memory_, sil_.data(), sil_.size(), s_sil, 1));
    std::vector<Ort::Value> out = state_.Run(Ort::RunOptions{nullptr}, in_names, in.data(), in.size(), out_names, 6);
    std::memcpy(st_.spkcache.data(), out[0].GetTensorData<float>(), st_.spkcache.size() * sizeof(float));
    std::memcpy(st_.spk_preds.data(), out[1].GetTensorData<float>(), st_.spk_preds.size() * sizeof(float));
    st_.sc_len = out[2].GetTensorData<int64_t>()[0];
    std::memcpy(st_.fifo.data(), out[3].GetTensorData<float>(), st_.fifo.size() * sizeof(float));
    st_.f_len = out[4].GetTensorData<int64_t>()[0];
    st_.compressed = out[5].GetTensorData<int64_t>()[0];
  }

  Ort::Env env_;
  Ort::MemoryInfo memory_;
  Ort::Session pre_{nullptr}, enc_{nullptr}, head_{nullptr}, state_{nullptr};
  std::vector<float> sil_;
  std::unique_ptr<MelStream> mel_;
  State st_;
  int64_t chunk_base_ = 0;
  bool preview_done_ = false;
  bool finished_ = false;
  const int preview_frames_;
  std::array<double, 4> load_ms_{};
};

// A session: engine plus the worker every call runs on, so calls serialize
// and the state machine only ever sees one Feed at a time.
struct Session {
  std::unique_ptr<Engine> engine;
  std::unique_ptr<RoleWorker> worker;
};

std::string RenderEvents(const std::vector<Event>& events, const Engine& engine) {
  std::ostringstream json;
  json << "{\"events\":[";
  for (size_t i = 0; i < events.size(); ++i) {
    const Event& e = events[i];
    if (i) json << ',';
    json << "{\"kind\":\"" << (e.preview ? "preview" : "final") << "\",\"beginFrame\":" << e.begin_frame
         << ",\"frames\":" << e.frames << ",\"inferenceMs\":" << e.inference_ms << ",\"runs\":[";
    for (int k = 0; k < kSpk; ++k) {
      if (k) json << ',';
      json << '[';
      for (size_t r = 0; r < e.runs[k].size(); ++r) {
        if (r) json << ',';
        json << '[' << e.runs[k][r].begin << ',' << e.runs[k][r].end << ']';
      }
      json << ']';
    }
    json << "]}";
  }
  json << "],\"melFrames\":" << engine.mel_frames() << ",\"samples\":" << engine.samples() << "}";
  return json.str();
}

// ------------------------------------------------------------- NAPI ---------

std::mutex sessions_mutex;
std::unordered_map<uint32_t, std::shared_ptr<Session>> sessions;
uint32_t next_handle = 1;

enum class Operation { Load, Feed };

struct Work {
  Operation operation;
  napi_async_work work = nullptr;
  napi_deferred deferred = nullptr;
  napi_env resource_env = nullptr;
  napi_ref resource_ref = nullptr;
  std::unique_ptr<NativeResourceManager, decltype(&OH_ResourceManager_ReleaseNativeResourceManager)>
    resource_manager{nullptr, OH_ResourceManager_ReleaseNativeResourceManager};
  int threads = 2;
  int role_qos = -1;
  int preview_frames = 0;
  std::shared_ptr<Session> session;
  std::vector<float> pcm;
  bool flush = false;
  uint32_t handle = 0;
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
      auto session = std::make_shared<Session>();
      session->worker = std::make_unique<RoleWorker>(task.role_qos);
      // Build on the worker so the ORT sessions' own threads inherit its policy.
      std::future<void> built = session->worker->Post([&] {
        session->engine = std::make_unique<Engine>(task.resource_manager.get(), task.threads, task.preview_frames);
      });
      built.get();
      std::lock_guard<std::mutex> lock(sessions_mutex);
      task.handle = next_handle++;
      sessions[task.handle] = session;
    } else {
      std::vector<Event> events;
      std::future<void> done = task.session->worker->Post([&] {
        events = task.session->engine->Feed(task.pcm, task.flush);
      });
      done.get();
      task.result = RenderEvents(events, *task.session->engine);
    }
  } catch (const Ort::Exception& error) {
    task.error = std::string("Sortformer onnxruntime: ") + error.what();
  } catch (const std::exception& error) {
    task.error = error.what();
  }
}

void Complete(napi_env env, napi_status, void* data) {
  std::unique_ptr<Work> task(static_cast<Work*>(data));
  napi_value value;
  if (!task->error.empty()) {
    napi_value message;
    napi_create_string_utf8(env, task->error.c_str(), NAPI_AUTO_LENGTH, &message);
    napi_create_error(env, nullptr, message, &value);
    napi_reject_deferred(env, task->deferred, value);
  } else if (task->operation == Operation::Load) {
    napi_create_uint32(env, task->handle, &value);
    napi_resolve_deferred(env, task->deferred, value);
  } else {
    napi_create_string_utf8(env, task->result.c_str(), NAPI_AUTO_LENGTH, &value);
    napi_resolve_deferred(env, task->deferred, value);
  }
  napi_delete_async_work(env, task->work);
}

std::string StringArgument(napi_env env, napi_value value, const char* fallback) {
  size_t length = 0;
  if (napi_get_value_string_utf8(env, value, nullptr, 0, &length) != napi_ok) return fallback;
  std::string text(length, '\0');
  size_t written = 0;
  if (napi_get_value_string_utf8(env, value, text.data(), length + 1, &written) != napi_ok) return fallback;
  text.resize(written);
  return text.empty() ? fallback : text;
}

std::vector<float> CopyFloat32Array(napi_env env, napi_value value) {
  napi_typedarray_type type;
  size_t length = 0, offset = 0;
  void* data = nullptr;
  napi_value buffer = nullptr;
  if (napi_get_typedarray_info(env, value, &type, &length, &data, &buffer, &offset) != napi_ok ||
      type != napi_float32_array) {
    throw std::runtime_error("Sortformer pcm must be a Float32Array");
  }
  // Some releases report bytes here rather than elements; trust the buffer.
  void* buffer_data = nullptr;
  size_t buffer_bytes = 0;
  if (napi_get_arraybuffer_info(env, buffer, &buffer_data, &buffer_bytes) != napi_ok || offset > buffer_bytes) {
    throw std::runtime_error("Sortformer pcm buffer is invalid");
  }
  napi_value byte_length_value;
  uint32_t bytes = 0;
  if (napi_get_named_property(env, value, "byteLength", &byte_length_value) != napi_ok ||
      napi_get_value_uint32(env, byte_length_value, &bytes) != napi_ok || bytes % sizeof(float) ||
      bytes > buffer_bytes - offset) {
    throw std::runtime_error("Sortformer pcm length is invalid");
  }
  const float* source = static_cast<const float*>(data);
  return std::vector<float>(source, source + bytes / sizeof(float));
}

napi_value Queue(napi_env env, napi_callback_info info, Operation operation) {
  size_t count = 5;
  napi_value args[5];
  napi_get_cb_info(env, info, &count, args, nullptr, nullptr);
  auto task = std::make_unique<Work>();
  task->operation = operation;
  try {
    if (operation == Operation::Load) {
      if (count < 1) throw std::runtime_error("resource manager is required");
      task->resource_manager.reset(OH_ResourceManager_InitNativeResourceManager(env, args[0]));
      if (!task->resource_manager) throw std::runtime_error("resource manager is invalid");
      task->resource_env = env;
      napi_create_reference(env, args[0], 1, &task->resource_ref);
      int32_t threads = 2;
      if (count >= 2 && napi_get_value_int32(env, args[1], &threads) == napi_ok) task->threads = std::clamp(threads, 1, 8);
      const std::string recognizer_qos = count >= 3 ? StringArgument(env, args[2], "default") : "default";
      const std::string role_qos = count >= 4 ? StringArgument(env, args[3], "inherit") : "inherit";
      task->role_qos = RoleQosOverride(role_qos, RoleQos(recognizer_qos));
      int32_t preview = 0;
      if (count >= 5 && napi_get_value_int32(env, args[4], &preview) == napi_ok) task->preview_frames = preview;
    } else {
      uint32_t handle = 0;
      if (count < 2 || napi_get_value_uint32(env, args[0], &handle) != napi_ok) {
        throw std::runtime_error("Sortformer handle is required");
      }
      {
        std::lock_guard<std::mutex> lock(sessions_mutex);
        auto it = sessions.find(handle);
        if (it == sessions.end()) throw std::runtime_error("Sortformer session is closed");
        task->session = it->second;
      }
      task->pcm = CopyFloat32Array(env, args[1]);
      bool flush = false;
      if (count >= 3 && napi_get_value_bool(env, args[2], &flush) == napi_ok) task->flush = flush;
    }
    napi_value promise;
    if (napi_create_promise(env, &task->deferred, &promise) != napi_ok) throw std::runtime_error("promise failed");
    napi_value name;
    napi_create_string_utf8(env, operation == Operation::Load ? "loadSortformerDiarization" : "feedSortformerDiarization",
                            NAPI_AUTO_LENGTH, &name);
    Work* raw = task.release();
    napi_create_async_work(env, nullptr, name, Execute, Complete, raw, &raw->work);
    napi_queue_async_work(env, raw->work);
    return promise;
  } catch (const std::exception& error) {
    napi_throw_error(env, nullptr, error.what());
    return nullptr;
  }
}

napi_value Load(napi_env env, napi_callback_info info) { return Queue(env, info, Operation::Load); }
napi_value FeedPcm(napi_env env, napi_callback_info info) { return Queue(env, info, Operation::Feed); }

napi_value Close(napi_env env, napi_callback_info info) {
  size_t count = 1;
  napi_value arg;
  napi_get_cb_info(env, info, &count, &arg, nullptr, nullptr);
  uint32_t handle = 0;
  if (count >= 1 && napi_get_value_uint32(env, arg, &handle) == napi_ok) {
    std::shared_ptr<Session> session;
    {
      std::lock_guard<std::mutex> lock(sessions_mutex);
      auto it = sessions.find(handle);
      if (it != sessions.end()) { session = it->second; sessions.erase(it); }
    }
    // In-flight async calls hold their own reference; the last one releases
    // the worker and the ORT sessions off the main thread.
  }
  napi_value result;
  napi_get_undefined(env, &result);
  return result;
}

}  // namespace

void RegisterSortformerDiarization(napi_env env, napi_value exports) {
  napi_property_descriptor methods[] = {
    {"loadSortformerDiarizationResources", nullptr, Load, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"feedSortformerDiarization", nullptr, FeedPcm, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"closeSortformerDiarization", nullptr, Close, nullptr, nullptr, nullptr, napi_default, nullptr},
  };
  napi_define_properties(env, exports, sizeof(methods) / sizeof(methods[0]), methods);
}
