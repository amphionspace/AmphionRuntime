#include "manifest.h"

#include <fstream>
#include <sstream>
#include <stdexcept>

#include <nlohmann/json.hpp>

namespace asr_service {

using json = nlohmann::json;

namespace {

template <typename T>
std::optional<T> get_optional(const json &j, const char *key) {
    if (!j.contains(key) || j.at(key).is_null()) return std::nullopt;
    return j.at(key).get<T>();
}

}  // namespace

Manifest LoadManifest(const std::string &path) {
    std::ifstream ifs(path);
    if (!ifs) {
        throw std::runtime_error("manifest file not found: " + path);
    }
    json j;
    ifs >> j;

    Manifest m;
    m.model_id = j.at("model_id").get<std::string>();
    m.version = j.at("version").get<std::string>();
    m.lang = j.value("lang", std::string("zh"));
    m.model_type = j.value("model_type", std::string("zipformer2"));
    m.model_dir = j.at("model_dir").get<std::string>();
    m.sample_rate = j.value("sample_rate", 16000);
    m.feature_dim = j.value("feature_dim", 80);
    m.decoding_method = get_optional<std::string>(j, "decoding_method");
    m.max_active_paths = get_optional<int>(j, "max_active_paths");
    m.homophone_lexicon = get_optional<std::string>(j, "homophone_lexicon");
    m.homophone_rule_fsts = get_optional<std::string>(j, "homophone_rule_fsts");
    if (j.contains("itn_rule_fsts") && j["itn_rule_fsts"].is_array()) {
        for (const auto &x : j["itn_rule_fsts"]) {
            m.itn_rule_fsts.push_back(x.get<std::string>());
        }
    }
    m.lm_model = get_optional<std::string>(j, "lm_model");
    m.lm_scale = get_optional<float>(j, "lm_scale");
    m.hotwords_file = get_optional<std::string>(j, "hotwords_file");
    m.hotwords_score = get_optional<float>(j, "hotwords_score");
    return m;
}

std::string ToJson(const Manifest &m) {
    json j;
    j["model_id"] = m.model_id;
    j["version"] = m.version;
    j["lang"] = m.lang;
    j["model_type"] = m.model_type;
    j["model_dir"] = m.model_dir;
    j["sample_rate"] = m.sample_rate;
    j["feature_dim"] = m.feature_dim;
    if (m.decoding_method) j["decoding_method"] = *m.decoding_method;
    if (m.max_active_paths) j["max_active_paths"] = *m.max_active_paths;
    if (m.homophone_lexicon) j["homophone_lexicon"] = *m.homophone_lexicon;
    if (m.homophone_rule_fsts) j["homophone_rule_fsts"] = *m.homophone_rule_fsts;
    if (!m.itn_rule_fsts.empty()) j["itn_rule_fsts"] = m.itn_rule_fsts;
    if (m.lm_model) j["lm_model"] = *m.lm_model;
    if (m.lm_scale) j["lm_scale"] = *m.lm_scale;
    if (m.hotwords_file) j["hotwords_file"] = *m.hotwords_file;
    if (m.hotwords_score) j["hotwords_score"] = *m.hotwords_score;
    return j.dump();
}

}  // namespace asr_service
