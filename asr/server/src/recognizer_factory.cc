#include "recognizer_factory.h"

#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace asr_service {

namespace {

std::string ResolveModelType(const std::string &raw) {
    if (raw == "zipformer" || raw == "zipformer2" || raw == "transducer" || raw.empty()) {
        return "transducer";
    }
    if (raw == "paraformer") return "paraformer";
    if (raw == "zipformer2_ctc" || raw == "zipformer2-ctc" || raw == "ctc") return "zipformer2_ctc";
    if (raw == "nemo_ctc" || raw == "nemo-ctc" || raw == "nemo") return "nemo_ctc";
    return "transducer";   // 未知按 transducer 兜底
}

std::string PickFirst(const std::string &dir, std::initializer_list<const char *> names) {
    for (auto n : names) {
        std::string p = dir + "/" + n;
        std::ifstream ifs(p);
        if (ifs.good()) return p;
    }
    return "";
}

// 按精度 + provider 选择模型文件。
// 根因：ONNX Runtime CUDA EP 对 int8(QDQ)支持差，量化算子常回退 CPU 并产生
// GPU<->CPU 拷贝；在 GPU 上应优先 fp16/fp32。CPU provider 则 int8 更省。
std::string PickByPrecision(const std::string &dir, const std::string &base,
                            const std::string &precision,
                            const std::string &provider) {
    const std::string i8 = base + ".int8.onnx";
    const std::string f32 = base + ".onnx";
    const std::string f16 = base + ".fp16.onnx";

    std::string p = precision;
    if (p.empty() || p == "auto") {
        p = (provider.find("cuda") != std::string::npos) ? "fp16" : "int8";
    }

    std::vector<std::string> order;
    if (p == "fp16") {
        order = {f16, f32, i8};
    } else if (p == "fp32") {
        order = {f32, f16, i8};
    } else {  // int8 兜底
        order = {i8, f32, f16};
    }
    for (const auto &name : order) {
        std::string full = dir + "/" + name;
        std::ifstream ifs(full);
        if (ifs.good()) return full;
    }
    return "";
}

}  // namespace

RecognizerFactory::RecognizerFactory(const Manifest &m, int num_threads,
                                     std::string provider,
                                     std::string encoder_precision,
                                     EndpointRules endpoint)
    : manifest_(m) {
    using namespace sherpa_onnx::cxx;

    OnlineRecognizerConfig config;

    // Feature
    config.feat_config.sample_rate = m.sample_rate;
    config.feat_config.feature_dim = m.feature_dim;

    // Model
    const std::string md = m.model_dir;
    config.model_config.tokens = md + "/tokens.txt";
    config.model_config.num_threads = num_threads;
    config.model_config.provider = provider;
    config.model_config.debug = false;
    config.model_config.model_type = m.model_type;

    const std::string normalized = ResolveModelType(m.model_type);
    if (normalized == "transducer") {
        config.model_config.transducer.encoder =
            PickByPrecision(md, "encoder", encoder_precision, provider);
        config.model_config.transducer.decoder = PickFirst(md, {
            "decoder.onnx", "decoder.int8.onnx"});
        config.model_config.transducer.joiner =
            PickByPrecision(md, "joiner", encoder_precision, provider);
        if (config.model_config.transducer.encoder.empty()
            || config.model_config.transducer.decoder.empty()
            || config.model_config.transducer.joiner.empty()) {
            throw std::runtime_error("missing transducer encoder/decoder/joiner under " + md);
        }
    } else if (normalized == "paraformer") {
        config.model_config.paraformer.encoder = PickFirst(md, {
            "encoder.int8.onnx", "encoder.onnx"});
        config.model_config.paraformer.decoder = PickFirst(md, {
            "decoder.int8.onnx", "decoder.onnx"});
        if (config.model_config.paraformer.encoder.empty()
            || config.model_config.paraformer.decoder.empty()) {
            throw std::runtime_error("missing paraformer encoder/decoder under " + md);
        }
    } else if (normalized == "zipformer2_ctc") {
        config.model_config.zipformer2_ctc.model =
            PickByPrecision(md, "ctc", encoder_precision, provider);
        if (config.model_config.zipformer2_ctc.model.empty()) {
            config.model_config.zipformer2_ctc.model = PickFirst(md, {
                "model.int8.onnx", "model.onnx"});
        }
        if (config.model_config.zipformer2_ctc.model.empty()) {
            throw std::runtime_error("missing zipformer2_ctc model under " + md);
        }
    } else if (normalized == "nemo_ctc") {
        config.model_config.nemo_ctc.model = PickFirst(md, {
            "model.int8.onnx", "model.onnx"});
        if (config.model_config.nemo_ctc.model.empty()) {
            throw std::runtime_error("missing nemo_ctc model under " + md);
        }
    }

    // Decoding
    config.decoding_method = m.decoding_method.value_or("greedy_search");
    if (normalized == "zipformer2_ctc" && config.decoding_method != "greedy_search") {
        std::cerr << "[recognizer] zipformer2_ctc supports greedy_search only; "
                  << "override decoding_method=" << config.decoding_method
                  << " to greedy_search" << std::endl;
        config.decoding_method = "greedy_search";
    }
    config.max_active_paths = m.max_active_paths.value_or(4);

    // Endpoint：默认与 Android / iOS 一致；服务端可通过启动参数统一覆盖。
    config.enable_endpoint = true;
    config.rule1_min_trailing_silence = endpoint.rule1_min_trailing_silence;
    config.rule2_min_trailing_silence = endpoint.rule2_min_trailing_silence;
    config.rule3_min_utterance_length = endpoint.rule3_min_utterance_length;

    // Hotwords
    if (m.hotwords_file) {
        config.hotwords_file = *m.hotwords_file;
    }
    config.hotwords_score = m.hotwords_score.value_or(1.5f);

    // 高级特性
    if (m.homophone_lexicon && m.homophone_rule_fsts) {
        config.hr.lexicon = *m.homophone_lexicon;
        config.hr.rule_fsts = *m.homophone_rule_fsts;
    }
    if (!m.itn_rule_fsts.empty()) {
        // sherpa-onnx 的 rule_fsts 字段是逗号分隔字符串
        std::string joined;
        for (size_t i = 0; i < m.itn_rule_fsts.size(); ++i) {
            if (i > 0) joined += ",";
            joined += m.itn_rule_fsts[i];
        }
        config.rule_fsts = joined;
    }
    if (m.lm_model) {
        std::cerr << "[recognizer] lm_model ignored: streaming cxx-api has no LM config"
                  << std::endl;
    }

    config_ = config;
    std::cerr << "[recognizer] configured model_id=" << m.model_id
              << " version=" << m.version
              << " model_type=" << m.model_type
              << " provider=" << provider
              << " num_threads=" << num_threads
              << " encoder_precision=" << encoder_precision
              << " encoder=" << config.model_config.transducer.encoder
              << " decoder=" << config.model_config.transducer.decoder
              << " joiner=" << config.model_config.transducer.joiner
              << " ctc_model=" << config.model_config.zipformer2_ctc.model
              << " decoding=" << config.decoding_method
              << " max_active_paths=" << config.max_active_paths
              << " endpoint_rule1=" << config.rule1_min_trailing_silence
              << " endpoint_rule2=" << config.rule2_min_trailing_silence
              << " endpoint_rule3=" << config.rule3_min_utterance_length
              << std::endl;
}

std::unique_ptr<sherpa_onnx::cxx::OnlineRecognizer>
RecognizerFactory::CreateRecognizer() const {
    using namespace sherpa_onnx::cxx;
    auto r = std::make_unique<OnlineRecognizer>(OnlineRecognizer::Create(config_));
    if (!r->Get()) {
        throw std::runtime_error(
            "OnlineRecognizer::Create failed for model_id=" + manifest_.model_id);
    }
    return r;
}

}  // namespace asr_service
