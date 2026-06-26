#include <csignal>
#include <algorithm>
#include <iostream>
#include <memory>

#include <grpcpp/grpcpp.h>
#include <grpcpp/ext/proto_server_reflection_plugin.h>
#include <grpcpp/health_check_service_interface.h>

#include "asr_service.h"
#include "decode_engine_pool.h"
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
    // 命令行覆盖（用于压测对照实验，不改 manifest 文件）
    if (!FLAGS_decoding_method.empty()) {
        manifest.decoding_method = FLAGS_decoding_method;
    }
    if (FLAGS_max_active_paths > 0) {
        manifest.max_active_paths = FLAGS_max_active_paths;
    }
    auto factory = std::make_shared<RecognizerFactory>(
        manifest, FLAGS_num_threads, FLAGS_provider, FLAGS_encoder_precision);
    auto engine = std::make_shared<DecodeEnginePool>(
        factory, FLAGS_decode_workers, FLAGS_max_batch_size, FLAGS_loop_interval_ms);
    auto metrics = std::make_shared<Metrics>(FLAGS_metrics_listen, manifest.model_id);

    // 2) 启动 gRPC server
    grpc::EnableDefaultHealthCheckService(true);
    grpc::reflection::InitProtoReflectionServerBuilderPlugin();

    AsrServiceImpl service(factory, engine, metrics,
                           FLAGS_max_concurrent_sessions,
                           FLAGS_session_idle_timeout_sec);

    grpc::ServerBuilder builder;
    const int grpc_threads = std::max(1, FLAGS_grpc_threads);
    builder.SetSyncServerOption(grpc::ServerBuilder::NUM_CQS,
                                std::max(1, grpc_threads / 4));
    builder.SetSyncServerOption(grpc::ServerBuilder::MIN_POLLERS,
                                grpc_threads);
    builder.SetSyncServerOption(grpc::ServerBuilder::MAX_POLLERS,
                                grpc_threads);
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
              << " version=" << manifest.version
              << " provider=" << FLAGS_provider
              << " encoder_precision=" << FLAGS_encoder_precision
              << " decode_workers=" << FLAGS_decode_workers
              << " num_threads=" << FLAGS_num_threads
              << " max_concurrent_sessions=" << FLAGS_max_concurrent_sessions
              << " max_batch_size=" << FLAGS_max_batch_size
              << " loop_interval_ms=" << FLAGS_loop_interval_ms
              << " grpc_threads=" << FLAGS_grpc_threads << std::endl;
    g_server->Wait();
    engine->Stop();
    std::cerr << "[main] grpc server stopped, bye" << std::endl;
    return 0;
}
