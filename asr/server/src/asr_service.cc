#include "asr_service.h"

#include <chrono>
#include <iostream>
#include <vector>

namespace asr_service {

namespace {

// 工具：把 AudioChunk.data + encoding 转成 [-1, 1] float 数组
std::vector<float> DecodePcm(const asr::v1::AudioChunk &chunk,
                             asr::v1::AudioEncoding encoding,
                             int channels) {
    std::vector<float> out;
    if (channels != 1) return out;
    const std::string &raw = chunk.data();
    if (encoding == asr::v1::PCM_S16LE) {
        const int16_t *ptr = reinterpret_cast<const int16_t *>(raw.data());
        size_t n = raw.size() / sizeof(int16_t);
        out.resize(n);
        for (size_t i = 0; i < n; ++i) {
            out[i] = static_cast<float>(ptr[i]) / 32768.0f;
        }
    } else if (encoding == asr::v1::PCM_F32LE) {
        const float *ptr = reinterpret_cast<const float *>(raw.data());
        size_t n = raw.size() / sizeof(float);
        out.assign(ptr, ptr + n);
    }
    return out;
}

void FillResult(asr::v1::AsrFinal *out,
                const sherpa_onnx::cxx::OnlineRecognizerResult &r,
                bool include_timestamps) {
    out->set_text(r.text);
    out->set_confidence(1.0f);   // sherpa-onnx 没暴露 segment confidence；后续可以接 ys_probs 几何均值
    if (include_timestamps) {
        for (const auto &t : r.tokens)     out->add_tokens(t);
        for (auto v : r.timestamps)         out->add_timestamps(v);
        // sherpa-onnx cxx-api 1.13.x 没有逐 token confidence；留空
    }
}

void FillPartial(asr::v1::AsrPartial *out,
                 const sherpa_onnx::cxx::OnlineRecognizerResult &r,
                 bool include_timestamps) {
    out->set_text(r.text);
    if (include_timestamps) {
        for (const auto &t : r.tokens) out->add_tokens(t);
        for (auto v : r.timestamps) out->add_timestamps(v);
    }
}

int64_t NowNs() {
    using namespace std::chrono;
    return duration_cast<nanoseconds>(steady_clock::now().time_since_epoch()).count();
}

}  // namespace

AsrServiceImpl::AsrServiceImpl(std::shared_ptr<RecognizerFactory> factory,
                               std::shared_ptr<Metrics> metrics,
                               int max_concurrent_sessions,
                               int session_idle_timeout_sec)
    : factory_(std::move(factory)),
      metrics_(std::move(metrics)),
      max_concurrent_sessions_(max_concurrent_sessions),
      session_idle_timeout_sec_(session_idle_timeout_sec),
      start_time_(std::chrono::steady_clock::now()) {}

grpc::Status AsrServiceImpl::Recognize(
    grpc::ServerContext *context,
    grpc::ServerReaderWriter<asr::v1::AsrEvent, asr::v1::PcmRequest> *stream) {
    if (active_sessions_.load() >= max_concurrent_sessions_) {
        return grpc::Status(grpc::StatusCode::RESOURCE_EXHAUSTED, "too many active sessions");
    }
    active_sessions_++;
    metrics_->active_sessions().Increment();
    auto active_guard = std::shared_ptr<void>(nullptr, [this](void *) {
        active_sessions_--;
        metrics_->active_sessions().Decrement();
    });

    auto *recognizer = factory_->get();
    if (!recognizer || !recognizer->Get()) {
        return grpc::Status(grpc::StatusCode::INTERNAL, "recognizer not loaded");
    }

    asr::v1::PcmRequest req;
    if (!stream->Read(&req)) {
        return grpc::Status(grpc::StatusCode::INVALID_ARGUMENT, "client closed before sending SessionConfig");
    }
    if (!req.has_session_config()) {
        return grpc::Status(grpc::StatusCode::INVALID_ARGUMENT, "first frame must be SessionConfig");
    }
    const auto &cfg = req.session_config();
    const int sr = cfg.audio_format().sample_rate();
    const auto encoding = cfg.audio_format().encoding();
    const int channels = cfg.audio_format().channels();
    const bool include_ts = cfg.include_token_timestamps();
    if (sr != factory_->manifest().sample_rate || channels != 1) {
        metrics_->error_total(1002).Increment();
        return grpc::Status(grpc::StatusCode::INVALID_ARGUMENT,
                            "audio_format mismatch with model manifest");
    }

    // 创建 stream（含初始热词）
    std::string hotwords = cfg.hotwords().words_text();
    auto sherpa_stream = recognizer->CreateStream(hotwords);

    // SessionStarted
    {
        asr::v1::AsrEvent ev;
        ev.set_server_send_ns(NowNs());
        ev.mutable_session_started();
        stream->Write(ev);
    }

    std::string last_partial;
    auto last_audio_time = std::chrono::steady_clock::now();
    bool client_finished = false;

    while (!client_finished) {
        if (!stream->Read(&req)) break;

        // 5 分钟无音频自动断流
        auto now = std::chrono::steady_clock::now();
        if (std::chrono::duration_cast<std::chrono::seconds>(now - last_audio_time).count()
            > session_idle_timeout_sec_) {
            asr::v1::AsrEvent ev;
            ev.mutable_error()->set_code(3003);
            ev.mutable_error()->set_message("session idle timeout");
            stream->Write(ev);
            metrics_->error_total(3003).Increment();
            break;
        }

        if (req.has_audio_chunk()) {
            last_audio_time = now;
            auto samples = DecodePcm(req.audio_chunk(), encoding, channels);
            if (samples.empty()) continue;

            auto t0 = std::chrono::steady_clock::now();
            sherpa_stream.AcceptWaveform(sr, samples.data(), static_cast<int>(samples.size()));
            while (recognizer->IsReady(&sherpa_stream)) {
                recognizer->Decode(&sherpa_stream);
            }
            auto t1 = std::chrono::steady_clock::now();
            double decode_ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
            double audio_ms = static_cast<double>(samples.size()) * 1000.0 / sr;
            metrics_->decode_latency_ms().Observe(decode_ms);
            if (audio_ms > 0) metrics_->rtf().Observe(decode_ms / audio_ms);

            // endpoint
            if (recognizer->IsEndpoint(&sherpa_stream)) {
                auto r = recognizer->GetResult(&sherpa_stream);
                {
                    asr::v1::AsrEvent ev;
                    ev.set_server_send_ns(NowNs());
                    ev.mutable_endpoint();
                    stream->Write(ev);
                }
                {
                    asr::v1::AsrEvent ev;
                    ev.set_server_send_ns(NowNs());
                    FillResult(ev.mutable_final_(), r, include_ts);
                    stream->Write(ev);
                    metrics_->final_total().Increment();
                }
                recognizer->Reset(&sherpa_stream);
                last_partial.clear();
            } else {
                auto r = recognizer->GetResult(&sherpa_stream);
                if (r.text != last_partial) {
                    last_partial = r.text;
                    asr::v1::AsrEvent ev;
                    ev.set_server_send_ns(NowNs());
                    FillPartial(ev.mutable_partial(), r, include_ts);
                    stream->Write(ev);
                    metrics_->partial_total().Increment();
                }
            }
        } else if (req.has_update_hotwords()) {
            // 重建 stream 应用新热词；当前未 final 的部分识别会被丢弃
            const auto &hw = req.update_hotwords().hotwords();
            sherpa_stream = recognizer->CreateStream(hw.words_text());
            last_partial.clear();
        } else if (req.has_end_of_stream()) {
            client_finished = true;
            sherpa_stream.InputFinished();
            while (recognizer->IsReady(&sherpa_stream)) {
                recognizer->Decode(&sherpa_stream);
            }
            auto r = recognizer->GetResult(&sherpa_stream);
            if (!r.text.empty()) {
                asr::v1::AsrEvent ev;
                ev.set_server_send_ns(NowNs());
                FillResult(ev.mutable_final_(), r, include_ts);
                stream->Write(ev);
                metrics_->final_total().Increment();
            }
        }
    }

    // SessionEnded
    {
        asr::v1::AsrEvent ev;
        ev.set_server_send_ns(NowNs());
        auto *e = ev.mutable_session_ended();
        e->set_trace_id(cfg.trace_id());
        stream->Write(ev);
    }
    return grpc::Status::OK;
}

grpc::Status AsrServiceImpl::Healthz(grpc::ServerContext *,
                                     const asr::v1::HealthzRequest *,
                                     asr::v1::HealthzResponse *resp) {
    resp->set_status(asr::v1::HealthzResponse::SERVING);
    resp->set_active_sessions(active_sessions_.load());
    return grpc::Status::OK;
}

grpc::Status AsrServiceImpl::ServerInfo(grpc::ServerContext *,
                                        const asr::v1::ServerInfoRequest *,
                                        asr::v1::ServerInfoResponse *resp) {
    resp->set_sdk_version("1.1.0");
    resp->set_sherpa_onnx_version("1.13.1");
    resp->set_model_manifest_json(ToJson(factory_->manifest()));
    auto uptime = std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::steady_clock::now() - start_time_).count();
    resp->set_uptime_seconds(uptime);
    return grpc::Status::OK;
}

}  // namespace asr_service
