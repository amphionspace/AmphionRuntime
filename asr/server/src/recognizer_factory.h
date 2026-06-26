#pragma once

#include <memory>
#include <string>

#include "manifest.h"
#include "sherpa-onnx/c-api/cxx-api.h"

namespace asr_service {

// 给定 manifest，保存可复用的 OnlineRecognizerConfig。
// 与 Android EngineImpl.buildOnlineRecognizerConfig / iOS EngineCore.buildRecognizerConfig 三端对齐。
// CreateRecognizer 每次构造一个独立的 OnlineRecognizer（独立 ORT session，进程内共享 CUDA context），
// 供单进程 recognizer 池按分片各持有一个使用。
class RecognizerFactory {
public:
    struct EndpointRules {
        float rule1_min_trailing_silence;
        float rule2_min_trailing_silence;
        float rule3_min_utterance_length;

        EndpointRules()
            : rule1_min_trailing_silence(2.4f),
              rule2_min_trailing_silence(1.2f),
              rule3_min_utterance_length(20.0f) {}
        EndpointRules(float rule1, float rule2, float rule3)
            : rule1_min_trailing_silence(rule1),
              rule2_min_trailing_silence(rule2),
              rule3_min_utterance_length(rule3) {}
    };

    explicit RecognizerFactory(const Manifest &m, int num_threads,
                               std::string provider,
                               std::string encoder_precision = "auto",
                               EndpointRules endpoint = EndpointRules());

    std::unique_ptr<sherpa_onnx::cxx::OnlineRecognizer> CreateRecognizer() const;
    const Manifest &manifest() const { return manifest_; }

private:
    Manifest manifest_;
    sherpa_onnx::cxx::OnlineRecognizerConfig config_;
};

}  // namespace asr_service
