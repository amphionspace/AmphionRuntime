#include <jni.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iterator>
#include <limits>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "onnxruntime_cxx_api.h"

namespace {

struct Utf8Char {
  std::string value;
  int32_t utf16_start = 0;
  int32_t utf16_end = 0;
};

struct PersonSpan {
  int32_t start = 0;
  int32_t end = 0;
};

class JStringChars {
 public:
  JStringChars(JNIEnv* env, jstring value) : env_(env), value_(value) {
    if (value_ == nullptr) throw std::invalid_argument("LAC path/text is required");
    chars_ = env_->GetStringUTFChars(value_, nullptr);
    if (chars_ == nullptr) throw std::runtime_error("failed to read LAC path/text");
  }
  ~JStringChars() {
    if (chars_ != nullptr) env_->ReleaseStringUTFChars(value_, chars_);
  }
  std::string str() const { return chars_; }

 private:
  JNIEnv* env_;
  jstring value_;
  const char* chars_ = nullptr;
};

void ThrowJava(JNIEnv* env, const std::string& message) {
  jclass type = env->FindClass("java/lang/IllegalStateException");
  if (type != nullptr) env->ThrowNew(type, message.c_str());
}

std::vector<Utf8Char> SplitUtf8(const std::string& text) {
  std::vector<Utf8Char> result;
  int32_t utf16_offset = 0;
  for (size_t i = 0; i < text.size();) {
    const uint8_t lead = static_cast<uint8_t>(text[i]);
    size_t width = 1;
    uint32_t codepoint = lead;
    if ((lead & 0xE0U) == 0xC0U) {
      width = 2;
      codepoint = lead & 0x1FU;
    } else if ((lead & 0xF0U) == 0xE0U) {
      width = 3;
      codepoint = lead & 0x0FU;
    } else if ((lead & 0xF8U) == 0xF0U) {
      width = 4;
      codepoint = lead & 0x07U;
    }
    if (i + width > text.size()) throw std::runtime_error("invalid UTF-8 input");
    for (size_t j = 1; j < width; ++j) {
      const uint8_t continuation = static_cast<uint8_t>(text[i + j]);
      if ((continuation & 0xC0U) != 0x80U) throw std::runtime_error("invalid UTF-8 input");
      codepoint = (codepoint << 6U) | (continuation & 0x3FU);
    }
    Utf8Char item;
    item.value = text.substr(i, width);
    item.utf16_start = utf16_offset;
    utf16_offset += codepoint > 0xFFFFU ? 2 : 1;
    item.utf16_end = utf16_offset;
    result.push_back(std::move(item));
    i += width;
  }
  return result;
}

std::unordered_map<std::string, std::string> LoadTsv(const std::string& path) {
  std::ifstream input(path);
  if (!input) throw std::runtime_error("failed to open LAC dictionary: " + path);
  std::unordered_map<std::string, std::string> result;
  std::string line;
  while (std::getline(input, line)) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    const size_t tab = line.find('\t');
    if (tab == std::string::npos) continue;
    result[line.substr(0, tab)] = line.substr(tab + 1);
  }
  return result;
}

uint16_t ReadLe16(const std::vector<uint8_t>& data, size_t offset) {
  if (offset + 2 > data.size()) throw std::runtime_error("invalid NPY header");
  return static_cast<uint16_t>(data[offset]) |
      (static_cast<uint16_t>(data[offset + 1]) << 8U);
}

uint32_t ReadLe32(const std::vector<uint8_t>& data, size_t offset) {
  if (offset + 4 > data.size()) throw std::runtime_error("invalid NPY header");
  return static_cast<uint32_t>(data[offset]) |
      (static_cast<uint32_t>(data[offset + 1]) << 8U) |
      (static_cast<uint32_t>(data[offset + 2]) << 16U) |
      (static_cast<uint32_t>(data[offset + 3]) << 24U);
}

std::vector<float> LoadTransitions(const std::string& path, int32_t* tag_count) {
  std::ifstream input(path, std::ios::binary);
  if (!input) throw std::runtime_error("failed to open LAC transitions: " + path);
  std::vector<uint8_t> data((std::istreambuf_iterator<char>(input)),
                            std::istreambuf_iterator<char>());
  const uint8_t magic[] = {0x93U, 'N', 'U', 'M', 'P', 'Y'};
  if (data.size() < 10 || !std::equal(std::begin(magic), std::end(magic), data.begin())) {
    throw std::runtime_error("invalid LAC transitions NPY magic");
  }
  const uint8_t major = data[6];
  const size_t header_size_offset = 8;
  const size_t header_size_width = major == 1 ? 2 : 4;
  const size_t header_length = major == 1 ? ReadLe16(data, header_size_offset) :
      ReadLe32(data, header_size_offset);
  const size_t payload_offset = header_size_offset + header_size_width + header_length;
  const std::string header(reinterpret_cast<const char*>(data.data() +
      header_size_offset + header_size_width), header_length);
  if (header.find("'<f4'") == std::string::npos ||
      header.find("'fortran_order': False") == std::string::npos) {
    throw std::runtime_error("LAC transitions must be little-endian C-order float32");
  }
  const size_t shape_start = header.find("'shape': (");
  if (shape_start == std::string::npos) throw std::runtime_error("LAC transitions shape missing");
  const size_t first_start = shape_start + 10;
  const size_t comma = header.find(',', first_start);
  const size_t close = header.find(')', comma);
  if (comma == std::string::npos || close == std::string::npos) {
    throw std::runtime_error("invalid LAC transitions shape");
  }
  const int32_t rows = std::stoi(header.substr(first_start, comma - first_start));
  const int32_t columns = std::stoi(header.substr(comma + 1, close - comma - 1));
  if (rows <= 0 || rows != columns) throw std::runtime_error("LAC transitions must be square");
  const size_t count = static_cast<size_t>(rows) * rows;
  if (payload_offset + count * sizeof(float) != data.size()) {
    throw std::runtime_error("LAC transitions payload size mismatch");
  }
  std::vector<float> result(count);
  std::memcpy(result.data(), data.data() + payload_offset, count * sizeof(float));
  *tag_count = rows;
  return result;
}

class LacPersonNer {
 public:
  LacPersonNer(const std::string& model_path, const std::string& transitions_path,
               const std::string& word_path, const std::string& tag_path,
               const std::string& q2b_path)
      : env_(ORT_LOGGING_LEVEL_WARNING, "amphion-lac-person") {
    const auto words = LoadTsv(word_path);
    for (const auto& entry : words) vocab_[entry.second] = std::stoll(entry.first);
    const auto oov = vocab_.find("OOV");
    oov_id_ = oov == vocab_.end() ? 0 : oov->second;
    const auto tags = LoadTsv(tag_path);
    transitions_ = LoadTransitions(transitions_path, &tag_count_);
    labels_.assign(tag_count_, "n-B");
    for (const auto& entry : tags) {
      const int32_t id = std::stoi(entry.first);
      if (id >= 0 && id < tag_count_) labels_[id] = entry.second;
    }
    q2b_ = LoadTsv(q2b_path);

    Ort::SessionOptions options;
    options.SetExecutionMode(ExecutionMode::ORT_SEQUENTIAL);
    options.SetIntraOpNumThreads(2);
    options.SetInterOpNumThreads(1);
    options.DisableMemPattern();
    options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
    session_ = Ort::Session(env_, model_path.c_str(), options);
    if (session_.GetInputCount() != 2 || session_.GetOutputCount() != 1) {
      throw std::runtime_error("unexpected LAC model input/output count");
    }
    Ort::AllocatorWithDefaultOptions allocator;
    for (size_t i = 0; i < session_.GetInputCount(); ++i) {
      const std::string name = session_.GetInputNameAllocated(i, allocator).get();
      if (name == "token_ids") token_input_index_ = static_cast<int32_t>(i);
      if (name == "length") length_input_index_ = static_cast<int32_t>(i);
    }
    if (token_input_index_ < 0 || length_input_index_ < 0) {
      throw std::runtime_error("LAC model inputs token_ids/length are missing");
    }
    output_name_ = session_.GetOutputNameAllocated(0, allocator).get();
  }

  std::vector<PersonSpan> FindPersonSpans(const std::string& text) {
    std::lock_guard<std::mutex> lock(mutex_);
    const std::vector<Utf8Char> chars = SplitUtf8(text);
    if (chars.empty()) return {};
    if (chars.size() > 512) throw std::runtime_error("LAC input exceeds 512 characters");
    std::vector<int64_t> ids;
    ids.reserve(chars.size());
    for (const Utf8Char& item : chars) {
      auto normalized = q2b_.find(item.value);
      const std::string& value = normalized == q2b_.end() ? item.value : normalized->second;
      const auto found = vocab_.find(value);
      ids.push_back(found == vocab_.end() ? oov_id_ : found->second);
    }
    int64_t length = static_cast<int64_t>(ids.size());
    std::array<int64_t, 2> ids_shape{1, length};
    std::array<int64_t, 1> length_shape{1};
    Ort::MemoryInfo memory = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    Ort::Value ids_tensor = Ort::Value::CreateTensor<int64_t>(
        memory, ids.data(), ids.size(), ids_shape.data(), ids_shape.size());
    Ort::Value length_tensor = Ort::Value::CreateTensor<int64_t>(
        memory, &length, 1, length_shape.data(), length_shape.size());
    std::array<const char*, 2> input_names{};
    std::array<Ort::Value, 2> inputs{std::move(ids_tensor), std::move(length_tensor)};
    input_names[token_input_index_] = "token_ids";
    input_names[length_input_index_] = "length";
    if (token_input_index_ != 0) std::swap(inputs[0], inputs[1]);
    const char* output_names[] = {output_name_.c_str()};
    std::vector<Ort::Value> outputs = session_.Run(
        Ort::RunOptions{nullptr}, input_names.data(), inputs.data(), inputs.size(), output_names, 1);
    if (outputs.size() != 1 || !outputs[0].IsTensor()) {
      throw std::runtime_error("LAC model returned an invalid output");
    }
    const auto shape = outputs[0].GetTensorTypeAndShapeInfo().GetShape();
    if (shape.size() != 3 || shape[0] != 1 || shape[1] != length || shape[2] != tag_count_) {
      throw std::runtime_error("unexpected LAC logits shape");
    }
    const std::vector<int32_t> path = Viterbi(outputs[0].GetTensorData<float>(), length);
    return DecodePersons(chars, path);
  }

 private:
  std::vector<int32_t> Viterbi(const float* emissions, int64_t length) const {
    std::vector<float> scores(emissions, emissions + tag_count_);
    std::vector<int32_t> backpointers(static_cast<size_t>(length - 1) * tag_count_);
    std::vector<float> next(tag_count_);
    for (int64_t t = 1; t < length; ++t) {
      for (int32_t current = 0; current < tag_count_; ++current) {
        float best_score = -std::numeric_limits<float>::infinity();
        int32_t best_previous = 0;
        for (int32_t previous = 0; previous < tag_count_; ++previous) {
          const float candidate = scores[previous] +
              transitions_[static_cast<size_t>(previous) * tag_count_ + current];
          if (candidate > best_score) {
            best_score = candidate;
            best_previous = previous;
          }
        }
        next[current] = best_score + emissions[static_cast<size_t>(t) * tag_count_ + current];
        backpointers[static_cast<size_t>(t - 1) * tag_count_ + current] = best_previous;
      }
      scores.swap(next);
    }
    int32_t best = static_cast<int32_t>(std::distance(
        scores.begin(), std::max_element(scores.begin(), scores.end())));
    std::vector<int32_t> path(length);
    path[length - 1] = best;
    for (int64_t t = length - 1; t > 0; --t) {
      path[t - 1] = backpointers[static_cast<size_t>(t - 1) * tag_count_ + path[t]];
    }
    return path;
  }

  std::vector<PersonSpan> DecodePersons(const std::vector<Utf8Char>& chars,
                                        const std::vector<int32_t>& path) const {
    std::vector<PersonSpan> result;
    size_t i = 0;
    while (i < chars.size()) {
      const std::string label = labels_[path[i]];
      const size_t dash = label.rfind('-');
      const std::string category = dash == std::string::npos ? label : label.substr(0, dash);
      const size_t start = i++;
      while (i < chars.size()) {
        const std::string& next = labels_[path[i]];
        if (next.size() < 2 || next.compare(next.size() - 2, 2, "-I") != 0) break;
        ++i;
      }
      if (category == "PER") {
        result.push_back(PersonSpan{chars[start].utf16_start, chars[i - 1].utf16_end});
      }
    }
    return result;
  }

  Ort::Env env_;
  Ort::Session session_{nullptr};
  std::unordered_map<std::string, int64_t> vocab_;
  std::unordered_map<std::string, std::string> q2b_;
  std::vector<std::string> labels_;
  std::vector<float> transitions_;
  int64_t oov_id_ = 0;
  int32_t tag_count_ = 0;
  int32_t token_input_index_ = -1;
  int32_t length_input_index_ = -1;
  std::string output_name_;
  std::mutex mutex_;
};

}  // namespace

extern "C" JNIEXPORT jlong JNICALL
Java_com_amphion_police_person_LacPersonNer_nativeCreate(
    JNIEnv* env, jobject, jstring model, jstring transitions, jstring word,
    jstring tag, jstring q2b) {
  try {
    return reinterpret_cast<jlong>(new LacPersonNer(
        JStringChars(env, model).str(), JStringChars(env, transitions).str(),
        JStringChars(env, word).str(), JStringChars(env, tag).str(),
        JStringChars(env, q2b).str()));
  } catch (const std::exception& error) {
    ThrowJava(env, error.what());
    return 0;
  }
}

extern "C" JNIEXPORT jintArray JNICALL
Java_com_amphion_police_person_LacPersonNer_nativeFindPersonSpans(
    JNIEnv* env, jobject, jlong handle, jstring text) {
  try {
    auto* ner = reinterpret_cast<LacPersonNer*>(handle);
    if (ner == nullptr) throw std::invalid_argument("LAC person NER is closed");
    const auto spans = ner->FindPersonSpans(JStringChars(env, text).str());
    std::vector<jint> flattened(spans.size() * 2);
    for (size_t i = 0; i < spans.size(); ++i) {
      flattened[i * 2] = spans[i].start;
      flattened[i * 2 + 1] = spans[i].end;
    }
    jintArray result = env->NewIntArray(static_cast<jsize>(flattened.size()));
    if (result != nullptr) {
      env->SetIntArrayRegion(result, 0, static_cast<jsize>(flattened.size()), flattened.data());
    }
    return result;
  } catch (const std::exception& error) {
    ThrowJava(env, error.what());
    return nullptr;
  }
}

extern "C" JNIEXPORT void JNICALL
Java_com_amphion_police_person_LacPersonNer_nativeClose(
    JNIEnv*, jobject, jlong handle) {
  delete reinterpret_cast<LacPersonNer*>(handle);
}
