#include "lits_tn_inprocess.hpp"

#include <cstdint>
#include <filesystem>
#include <map>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>

#include <unicode/fieldpos.h>
#include <unicode/locid.h>
#include <unicode/rbnf.h>
#include <unicode/unistr.h>

#include "tts_normalizer_engine.hpp"

namespace {

class BaseNormalizer {
 public:
  virtual ~BaseNormalizer() = default;
  virtual std::string Normalize(const std::string& input) = 0;
};

class ZhNormalizer final : public BaseNormalizer {
 public:
  explicit ZhNormalizer(const std::string& root_dir) {
    UErrorCode status = U_ZERO_ERROR;
    spellout_fmt_ = std::make_unique<icu::RuleBasedNumberFormat>(
        icu::URBNF_SPELLOUT, icu::Locale::getChinese(), status);
    if (U_FAILURE(status)) {
      throw std::runtime_error("failed to initialize zh spellout formatter");
    }

    std::string err;
    const auto root = std::filesystem::path(root_dir);
    if (!engine_.loadRulesV2((root / "rules_v2" / "zh.full.json").string(), err)) {
      throw std::runtime_error("failed to load zh rules_v2: " + err);
    }
    if (!engine_.loadPinyinMap((root / "rules" / "zh_pinyin.json").string(), err)) {
      throw std::runtime_error("failed to load zh pinyin map: " + err);
    }
  }

  std::string Normalize(const std::string& input) override {
    icu::UnicodeString text = icu::UnicodeString::fromUTF8(input);
    TtsCallbacks cb;
    cb.spellout = [this](const icu::UnicodeString& n) { return NumberToChinese(n); };
    text = engine_.runPipeline(text, cb);
    std::string output;
    text.toUTF8String(output);
    return output;
  }

 private:
  icu::UnicodeString NumberToChinese(const icu::UnicodeString& num_str) {
    UErrorCode status = U_ZERO_ERROR;
    std::string utf8_num;
    num_str.toUTF8String(utf8_num);
    try {
      double value = std::stod(utf8_num);
      icu::UnicodeString result;
      spellout_fmt_->format(value, result, status);
      return result;
    } catch (...) {
      return num_str;
    }
  }

  TtsNormalizerEngine engine_;
  std::unique_ptr<icu::RuleBasedNumberFormat> spellout_fmt_;
};

class EnNormalizer final : public BaseNormalizer {
 public:
  explicit EnNormalizer(const std::string& root_dir) {
    UErrorCode status = U_ZERO_ERROR;
    spellout_fmt_ = std::make_unique<icu::RuleBasedNumberFormat>(
        icu::URBNF_SPELLOUT, icu::Locale::getEnglish(), status);
    if (U_FAILURE(status)) {
      throw std::runtime_error("failed to initialize en spellout formatter");
    }

    std::string err;
    const auto root = std::filesystem::path(root_dir);
    if (!engine_.loadRulesV2((root / "rules_v2" / "en.full.json").string(), err)) {
      throw std::runtime_error("failed to load en rules_v2: " + err);
    }
    engine_.loadPinyinMap("", err);
  }

  std::string Normalize(const std::string& input) override {
    icu::UnicodeString text = icu::UnicodeString::fromUTF8(input);
    TtsCallbacks cb;
    cb.spellout = [this](const icu::UnicodeString& n) { return NumberToEnglish(n); };
    cb.ordinal_spellout = [this](const icu::UnicodeString& n, UErrorCode& st) {
      return NumberToOrdinalEnglish(n, st);
    };
    text = engine_.runPipeline(text, cb);
    std::string output;
    text.toUTF8String(output);
    return output;
  }

 private:
  icu::UnicodeString NumberToEnglish(const icu::UnicodeString& num_str) {
    UErrorCode status = U_ZERO_ERROR;
    std::string utf8_num;
    num_str.toUTF8String(utf8_num);
    try {
      double value = std::stod(utf8_num);
      icu::UnicodeString result;
      spellout_fmt_->format(value, result, status);
      return result;
    } catch (...) {
      return num_str;
    }
  }

  icu::UnicodeString NumberToOrdinalEnglish(const icu::UnicodeString& num_str, UErrorCode& status) {
    if (U_FAILURE(status)) {
      return num_str;
    }
    icu::RuleBasedNumberFormat formatter(icu::URBNF_SPELLOUT, icu::Locale::getEnglish(), status);
    if (U_FAILURE(status)) {
      return icu::UnicodeString();
    }
    std::string utf8;
    num_str.toUTF8String(utf8);
    int64_t value = 0;
    try {
      value = std::stoll(utf8);
    } catch (...) {
      status = U_PARSE_ERROR;
      return icu::UnicodeString();
    }
    const icu::UnicodeString rule_set("%spellout-ordinal");
    icu::UnicodeString result;
    icu::FieldPosition pos(icu::FieldPosition::DONT_CARE);
    formatter.format(value, rule_set, result, pos, status);
    return result;
  }

  TtsNormalizerEngine engine_;
  std::unique_ptr<icu::RuleBasedNumberFormat> spellout_fmt_;
};

std::mutex g_normalizers_mutex;
std::map<std::string, std::unique_ptr<BaseNormalizer>> g_normalizers;

}  // namespace

std::string NormalizeTnInProcess(const std::string& root_dir, const std::string& lang, const std::string& text) {
  if (text.empty()) {
    return text;
  }

  const std::string normalized_lang = lang == "en" ? "en" : "zh";
  const std::string key = root_dir + "\n" + normalized_lang;
  std::lock_guard<std::mutex> lock(g_normalizers_mutex);
  auto& normalizer = g_normalizers[key];
  if (!normalizer) {
    if (normalized_lang == "en") {
      normalizer = std::make_unique<EnNormalizer>(root_dir);
    } else {
      normalizer = std::make_unique<ZhNormalizer>(root_dir);
    }
  }
  return normalizer->Normalize(text);
}
