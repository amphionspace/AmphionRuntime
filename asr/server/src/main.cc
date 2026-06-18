#include <csignal>
#include <iostream>
#include <memory>

#include <grpcpp/grpcpp.h>
#include <grpcpp/ext/proto_server_reflection_plugin.h>
#include <grpcpp/health_check_service_interface.h>

#include "asr_service.h"
#include "flags.h"
#include "manifest.h"
#include "metrics.h"
#include "recognizer_factory.h"

namespace {

std::shared_ptr<grpc::Server> g_server;

void HandleSignal(int sig) {
    std::cerr << "[main] caught signal " << sig << ", shutting down ..." << std::endl;
    if (g_server) {
        g_server->Shutdown(std::chrono::system_clock::now() + std::chrono::seconds(5));
    }
}

}  // namespace

int main(int argc, char **argv) {
    gflags::ParseCommandLineFlags(&argc, &argv, true);

    using namespace asr_service;

    // 1) 加载 manifest + 初始化 OnlineRecognizer
    auto manifest = LoadManifest(FLAGS_manifest);
    auto factory = std::make_shared<RecognizerFactory>(manifest, FLAGS_num_threads);
    auto metrics = std::make_shared<Metrics>(FLAGS_metrics_listen, manifest.model_id);

    // 2) 启动 gRPC server
    grpc::EnableDefaultHealthCheckService(true);
    grpc::reflection::InitProtoReflectionServerBuilderPlugin();

    AsrServiceImpl service(factory, metrics,
                           FLAGS_max_concurrent_sessions,
                           FLAGS_session_idle_timeout_sec);

    grpc::ServerBuilder builder;
    builder.AddListeningPort(FLAGS_listen, grpc::InsecureServerCredentials());
    builder.RegisterService(&service);
    builder.SetMaxReceiveMessageSize(8 * 1024 * 1024);
    builder.SetMaxSendMessageSize(8 * 1024 * 1024);
    auto server = builder.BuildAndStart();
    if (!server) {
        std::cerr << "[main] failed to start grpc server on " << FLAGS_listen << std::endl;
        return 1;
    }
    g_server = std::shared_ptr<grpc::Server>(std::move(server));

    std::signal(SIGINT, HandleSignal);
    std::signal(SIGTERM, HandleSignal);

    std::cerr << "[main] listening on " << FLAGS_listen
              << " model_id=" << manifest.model_id
              << " version=" << manifest.version << std::endl;
    g_server->Wait();
    std::cerr << "[main] grpc server stopped, bye" << std::endl;
    return 0;
}
