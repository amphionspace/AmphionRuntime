#include <unistd.h>

#include <csignal>
#include <algorithm>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

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

constexpr const char *kServerVersion = "1.1.0";

std::shared_ptr<grpc::Server> g_server;

void HandleSignal(int sig) {
    std::cerr << "[main] caught signal " << sig << ", shutting down ..." << std::endl;
    if (g_server) {
        g_server->Shutdown(std::chrono::system_clock::now() + std::chrono::seconds(5));
    }
}

// 计算字符串可见宽度：跳过 ANSI 颜色转义（\033[...m），其余按 1 列计。
// banner 内容均为 ASCII（+可选颜色码），故字符数即显示宽度。
size_t VisibleLen(const std::string &s) {
    size_t n = 0;
    for (size_t i = 0; i < s.size(); ++i) {
        if (s[i] == '\033') {
            while (i < s.size() && s[i] != 'm') ++i;
        } else {
            ++n;
        }
    }
    return n;
}

// 打印 vLLM 风格的启动横幅：框线汇总监听地址与关键配置，一眼可见。
// 仅在 stderr 为 TTY 时上色，重定向到文件时输出纯文本，避免乱码。
void PrintStartupBanner(const std::string &title,
                        const std::vector<std::string> &rows) {
    const bool color = isatty(fileno(stderr));
    const std::string CY = color ? "\033[36m" : "";  // 边框：青色
    const std::string BD = color ? "\033[1m" : "";   // 标题：加粗
    const std::string RS = color ? "\033[0m" : "";

    size_t w = VisibleLen(title);
    for (const auto &r : rows) w = std::max(w, VisibleLen(r));

    std::string bar;
    for (size_t i = 0; i < w + 2; ++i) bar += "═";

    std::ostringstream o;
    o << "\n" << CY << "╔" << bar << "╗" << RS << "\n";

    const size_t tlen = VisibleLen(title);
    const size_t lpad = (w - tlen) / 2;
    const size_t rpad = w - tlen - lpad;
    o << CY << "║" << RS << " " << std::string(lpad, ' ')
      << BD << title << RS << std::string(rpad, ' ') << " "
      << CY << "║" << RS << "\n";

    o << CY << "╠" << bar << "╣" << RS << "\n";
    for (const auto &r : rows) {
        o << CY << "║" << RS << " " << r
          << std::string(w - VisibleLen(r), ' ') << " "
          << CY << "║" << RS << "\n";
    }
    o << CY << "╚" << bar << "╝" << RS << "\n";
    std::cerr << o.str() << std::flush;
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
    RecognizerFactory::EndpointRules endpoint_rules{
        static_cast<float>(FLAGS_endpoint_rule1_min_trailing_silence),
        static_cast<float>(FLAGS_endpoint_rule2_min_trailing_silence),
        static_cast<float>(FLAGS_endpoint_rule3_min_utterance_length)};
    auto factory = std::make_shared<RecognizerFactory>(
        manifest, FLAGS_num_threads, FLAGS_provider, FLAGS_encoder_precision,
        endpoint_rules);
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

    {
        const bool tty = isatty(fileno(stderr));
        auto col = [](const std::string &l, const std::string &v) {
            std::ostringstream o;
            o << std::left << std::setw(14) << l << ": " << v;
            return o.str();
        };
        auto col2 = [](const std::string &l1, const std::string &v1,
                       const std::string &l2, const std::string &v2) {
            std::ostringstream o;
            o << std::left << std::setw(14) << l1 << ": " << std::setw(22) << v1
              << std::setw(12) << l2 << ": " << v2;
            return o.str();
        };
        auto sec = [](double v) {
            std::ostringstream o;
            o << std::fixed << std::setprecision(2) << v;
            std::string s = o.str();
            while (s.size() > 1 && s.back() == '0') s.pop_back();
            if (!s.empty() && s.back() == '.') s.push_back('0');
            return s + "s";
        };
        std::ostringstream st;
        st << std::left << std::setw(14) << "status" << ": "
           << (tty ? "\033[32mREADY\033[0m" : "READY");

        const std::string dec_method =
            manifest.decoding_method.value_or("greedy_search");
        const int max_paths = manifest.max_active_paths.value_or(4);

        std::vector<std::string> rows = {
            col("gRPC listen", FLAGS_listen),
            st.str(),
            col("model", manifest.model_id),
            col("version", manifest.version),
            col2("provider", FLAGS_provider, "precision", FLAGS_encoder_precision),
            col2("decoding", dec_method, "beam", std::to_string(max_paths)),
            col("endpoint", "r1=" + sec(FLAGS_endpoint_rule1_min_trailing_silence)
                            + " r2=" + sec(FLAGS_endpoint_rule2_min_trailing_silence)
                            + " r3=" + sec(FLAGS_endpoint_rule3_min_utterance_length)),
            col2("decode_workers", std::to_string(FLAGS_decode_workers),
                 "num_threads", std::to_string(FLAGS_num_threads)),
            col2("max_sessions", std::to_string(FLAGS_max_concurrent_sessions),
                 "max_batch", std::to_string(FLAGS_max_batch_size)),
            col2("grpc_threads", std::to_string(FLAGS_grpc_threads),
                 "loop_ms", std::to_string(FLAGS_loop_interval_ms)),
            col2("language", manifest.lang,
                 "sample_rate", std::to_string(manifest.sample_rate) + " Hz"),
        };
        PrintStartupBanner(
            std::string("AmphionRuntime ASR Server  v") + kServerVersion, rows);
    }
    g_server->Wait();
    engine->Stop();
    std::cerr << "[main] grpc server stopped, bye" << std::endl;
    return 0;
}
