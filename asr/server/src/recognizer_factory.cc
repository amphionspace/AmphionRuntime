#include "recognizer_factory.h"

#include <iostream>
#include <stdexcept>

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

}  // namespace

RecognizerFactory::RecognizerFactory(const Manifest &m, int num_threads)
    : manifest_(m), recognizer_() {
    using namespace sherpa_onnx::cxx;

    OnlineRecognizerConfig config;

    // Feature
    config.feat_config.sample_rate = m.sample_rate;
    config.feat_config.feature_dim = m.feature_dim;

    // Model
    const std::string md = m.model_dir;
    config.model_config.tokens = md + "/tokens.txt";
    config.model_config.num_threads = num_threads;
    config.model_config.provider = "cpu";
    config.model_config.debug = false;
    config.model_config.model_type = m.model_type;

    const std::string normalized = ResolveModelType(m.model_type);
    if (normalized == "transducer") {
        config.model_config.transducer.encoder = PickFirst(md, {
            "encoder.int8.onnx", "encoder.onnx", "encoder.fp16.onnx"});
        config.model_config.transducer.decoder = PickFirst(md, {
            "decoder.onnx", "decoder.int8.onnx"});
        config.model_config.transducer.joiner = PickFirst(md, {
            "joiner.int8.onnx", "joiner.onnx", "joiner.fp16.onnx"});
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
        config.model_config.zipformer2_ctc.model = PickFirst(md, {
            "model.int8.onnx", "model.onnx"});
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
    config.max_active_paths = m.max_active_paths.value_or(4);

    // Endpoint：使用与 Android / iOS 一致的默认值
    config.enable_endpoint = true;
    config.endpoint_config.rule1.min_trailing_silence = 2.4f;
    config.endpoint_config.rule2.min_trailing_silence = 1.2f;
    config.endpoint_config.rule3.min_utterance_length = 20.0f;

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
        config.lm_config.model = *m.lm_model;
        config.lm_config.scale = m.lm_scale.value_or(0.5f);
    }

    recognizer_ = OnlineRecognizer::Create(config);
    if (!recognizer_.Get()) {
        throw std::runtime_error("OnlineRecognizer::Create failed for model_id=" + m.model_id);
    }
    std::cerr << "[recognizer] loaded model_id=" << m.model_id
              << " version=" << m.version
              << " model_type=" << m.model_type
              << " decoding=" << config.decoding_method
              << std::endl;
}

}  // namespace asr_service
