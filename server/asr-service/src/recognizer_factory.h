#pragma once

#include <memory>
#include <string>

#include "manifest.h"
#include "sherpa-onnx/c-api/cxx-api.h"

namespace asr_service {

// 给定 manifest，构造 sherpa_onnx::cxx::OnlineRecognizer + 必要的辅助。
// 与 Android EngineImpl.buildOnlineRecognizerConfig / iOS EngineCore.buildRecognizerConfig 三端对齐。
class RecognizerFactory {
public:
    explicit RecognizerFactory(const Manifest &m, int num_threads);

    sherpa_onnx::cxx::OnlineRecognizer *get() { return &recognizer_; }
    const Manifest &manifest() const { return manifest_; }

private:
    Manifest manifest_;
    sherpa_onnx::cxx::OnlineRecognizer recognizer_;
};

}  // namespace asr_service
