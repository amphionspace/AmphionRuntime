// Prometheus exporter；进程级单例。
#pragma once

#include <memory>
#include <string>

#include <prometheus/counter.h>
#include <prometheus/exposer.h>
#include <prometheus/family.h>
#include <prometheus/gauge.h>
#include <prometheus/registry.h>
#include <prometheus/summary.h>

namespace asr_service {

class Metrics {
public:
    // listen 为空表示不启动 exporter；其它情况会绑定 listen，并暴露 /metrics
    explicit Metrics(const std::string &listen, const std::string &model_id);

    prometheus::Gauge &active_sessions() { return *active_sessions_; }
    prometheus::Counter &partial_total() { return *partial_total_; }
    prometheus::Counter &final_total() { return *final_total_; }
    prometheus::Summary &rtf() { return *rtf_; }
    prometheus::Summary &decode_latency_ms() { return *decode_latency_ms_; }
    prometheus::Counter &error_total(int code);

private:
    std::shared_ptr<prometheus::Registry> registry_;
    std::unique_ptr<prometheus::Exposer> exposer_;

    prometheus::Family<prometheus::Gauge> *fam_active_;
    prometheus::Family<prometheus::Counter> *fam_partial_;
    prometheus::Family<prometheus::Counter> *fam_final_;
    prometheus::Family<prometheus::Summary> *fam_rtf_;
    prometheus::Family<prometheus::Summary> *fam_decode_;
    prometheus::Family<prometheus::Counter> *fam_error_;

    prometheus::Gauge *active_sessions_;
    prometheus::Counter *partial_total_;
    prometheus::Counter *final_total_;
    prometheus::Summary *rtf_;
    prometheus::Summary *decode_latency_ms_;

    std::string model_id_;
};

}  // namespace asr_service
