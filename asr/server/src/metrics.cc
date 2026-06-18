#include "metrics.h"

#include <iostream>

namespace asr_service {

namespace {

const prometheus::Summary::Quantiles kQuantiles = {
    {0.5,  0.05},
    {0.9,  0.01},
    {0.99, 0.001},
};

}  // namespace

Metrics::Metrics(const std::string &listen, const std::string &model_id)
    : registry_(std::make_shared<prometheus::Registry>()), model_id_(model_id) {
    fam_active_ = &prometheus::BuildGauge()
                       .Name("asr_active_sessions")
                       .Help("Number of active streaming sessions")
                       .Register(*registry_);
    fam_partial_ = &prometheus::BuildCounter()
                        .Name("asr_partial_total")
                        .Help("Number of partial results emitted")
                        .Register(*registry_);
    fam_final_ = &prometheus::BuildCounter()
                      .Name("asr_final_total")
                      .Help("Number of final results emitted")
                      .Register(*registry_);
    fam_rtf_ = &prometheus::BuildSummary()
                    .Name("asr_rtf")
                    .Help("Real-time factor (decode_time / audio_duration)")
                    .Register(*registry_);
    fam_decode_ = &prometheus::BuildSummary()
                       .Name("asr_decode_latency_ms")
                       .Help("Per-chunk decode latency in milliseconds")
                       .Register(*registry_);
    fam_error_ = &prometheus::BuildCounter()
                      .Name("asr_error_total")
                      .Help("Number of errors broken down by code")
                      .Register(*registry_);

    active_sessions_   = &fam_active_->Add({{"model_id", model_id}});
    partial_total_     = &fam_partial_->Add({{"model_id", model_id}});
    final_total_       = &fam_final_->Add({{"model_id", model_id}});
    rtf_               = &fam_rtf_->Add({{"model_id", model_id}}, kQuantiles);
    decode_latency_ms_ = &fam_decode_->Add({{"model_id", model_id}}, kQuantiles);

    if (!listen.empty()) {
        try {
            exposer_ = std::make_unique<prometheus::Exposer>(listen);
            exposer_->RegisterCollectable(registry_);
            std::cerr << "[metrics] exposing on " << listen << "/metrics" << std::endl;
        } catch (const std::exception &e) {
            std::cerr << "[metrics] exposer failed: " << e.what() << std::endl;
        }
    }
}

prometheus::Counter &Metrics::error_total(int code) {
    return fam_error_->Add({
        {"model_id", model_id_},
        {"code", std::to_string(code)},
    });
}

}  // namespace asr_service
