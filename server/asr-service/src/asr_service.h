#pragma once

#include <atomic>
#include <chrono>
#include <memory>
#include <string>

#include <grpcpp/grpcpp.h>

#include "asr.grpc.pb.h"
#include "metrics.h"
#include "recognizer_factory.h"

namespace asr_service {

class AsrServiceImpl final : public asr::v1::AsrService::Service {
public:
    AsrServiceImpl(std::shared_ptr<RecognizerFactory> factory,
                   std::shared_ptr<Metrics> metrics,
                   int max_concurrent_sessions,
                   int session_idle_timeout_sec);

    grpc::Status Recognize(
        grpc::ServerContext *context,
        grpc::ServerReaderWriter<asr::v1::AsrEvent, asr::v1::PcmRequest> *stream) override;

    grpc::Status Healthz(grpc::ServerContext *,
                         const asr::v1::HealthzRequest *,
                         asr::v1::HealthzResponse *resp) override;

    grpc::Status ServerInfo(grpc::ServerContext *,
                            const asr::v1::ServerInfoRequest *,
                            asr::v1::ServerInfoResponse *resp) override;

private:
    std::shared_ptr<RecognizerFactory> factory_;
    std::shared_ptr<Metrics> metrics_;
    int max_concurrent_sessions_;
    int session_idle_timeout_sec_;

    std::atomic<int> active_sessions_{0};
    std::chrono::steady_clock::time_point start_time_;
};

}  // namespace asr_service
