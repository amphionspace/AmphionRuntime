// 与 shared/api-spec/manifest.schema.json 对齐的服务端 model manifest。
#pragma once

#include <optional>
#include <string>
#include <vector>

namespace asr_service {

struct Manifest {
    std::string model_id;
    std::string version;
    std::string lang;
    std::string model_type;            // 与 ModelType 一致：zipformer/zipformer2/paraformer/...
    std::string model_dir;              // 模型文件本地目录（绝对路径）
    int sample_rate = 16000;
    int feature_dim = 80;
    std::optional<std::string> decoding_method;   // greedy_search / modified_beam_search
    std::optional<int> max_active_paths;
    // 可选高级特性资源（绝对路径）
    std::optional<std::string> homophone_lexicon;
    std::optional<std::string> homophone_rule_fsts;
    std::vector<std::string> itn_rule_fsts;
    std::optional<std::string> lm_model;
    std::optional<float> lm_scale;
    std::optional<std::string> hotwords_file;
    std::optional<float> hotwords_score;
};

// 从 path 加载 manifest.json；失败抛 std::runtime_error。
Manifest LoadManifest(const std::string &path);

// 把 manifest 序列化成 JSON，便于 ServerInfo 直接回给客户端。
std::string ToJson(const Manifest &m);

}  // namespace asr_service
