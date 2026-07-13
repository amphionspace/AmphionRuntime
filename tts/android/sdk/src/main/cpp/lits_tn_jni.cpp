#include <jni.h>

#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>

#include <android/log.h>
#include <unicode/locid.h>
#include <unicode/rbnf.h>
#include <unicode/unistr.h>

#include "tts_normalizer_engine.hpp"

namespace {

constexpr const char* kLogTag = "LitsTnNative";

std::string ToUtf8(JNIEnv* env, jstring value) {
    if (value == nullptr) {
        return "";
    }
    const char* chars = env->GetStringUTFChars(value, nullptr);
    if (chars == nullptr) {
        return "";
    }
    std::string output(chars);
    env->ReleaseStringUTFChars(value, chars);
    return output;
}

jstring ToJString(JNIEnv* env, const std::string& value) {
    return env->NewStringUTF(value.c_str());
}

class NativeTnNormalizer {
public:
    NativeTnNormalizer(std::string rules_root, std::string lang)
        : rules_root_(std::move(rules_root)),
          lang_(std::move(lang)) {
        UErrorCode status = U_ZERO_ERROR;
        const icu::Locale locale = lang_ == "en" ? icu::Locale::getEnglish() : icu::Locale::getChinese();
        spellout_fmt_ = std::make_unique<icu::RuleBasedNumberFormat>(icu::URBNF_SPELLOUT, locale, status);
        if (U_FAILURE(status)) {
            throw std::runtime_error("failed to create ICU RBNF spellout formatter");
        }

        std::string err;
        const std::string rules_path = rules_root_ + "/rules_v2/" + lang_ + ".full.json";
        if (!engine_.loadRulesV2(rules_path, err)) {
            throw std::runtime_error("failed to load TN rules_v2: " + err);
        }
        if (lang_ == "zh") {
            const std::string pinyin_path = rules_root_ + "/rules_v2/zh_pinyin.json";
            if (!engine_.loadPinyinMap(pinyin_path, err)) {
                throw std::runtime_error("failed to load TN pinyin map: " + err);
            }
        } else {
            engine_.loadPinyinMap("", err);
        }
    }

    std::string Normalize(const std::string& input_utf8) {
        icu::UnicodeString text = icu::UnicodeString::fromUTF8(input_utf8);
        TtsCallbacks callbacks;
        callbacks.spellout = [this](const icu::UnicodeString& n) {
            return NumberToSpellout(n);
        };
        callbacks.ordinal_spellout = [this](const icu::UnicodeString& n, UErrorCode& status) {
            if (lang_ == "en") {
                return NumberToOrdinalEnglish(n, status);
            }
            (void)status;
            return NumberToSpellout(n);
        };
        text = engine_.runPipeline(text, callbacks);
        std::string output;
        text.toUTF8String(output);
        return output;
    }

private:
    std::string rules_root_;
    std::string lang_;
    std::unique_ptr<icu::RuleBasedNumberFormat> spellout_fmt_;
    TtsNormalizerEngine engine_;

    icu::UnicodeString NumberToSpellout(const icu::UnicodeString& number) {
        UErrorCode status = U_ZERO_ERROR;
        std::string utf8;
        number.toUTF8String(utf8);
        try {
            const double value = std::stod(utf8);
            icu::UnicodeString result;
            spellout_fmt_->format(value, result, status);
            if (U_FAILURE(status)) {
                return number;
            }
            return result;
        } catch (...) {
            return number;
        }
    }

    icu::UnicodeString NumberToOrdinalEnglish(const icu::UnicodeString& number, UErrorCode& status) {
        if (U_FAILURE(status)) {
            return number;
        }
        icu::RuleBasedNumberFormat formatter(icu::URBNF_SPELLOUT, icu::Locale::getEnglish(), status);
        if (U_FAILURE(status)) {
            return icu::UnicodeString();
        }
        std::string utf8;
        number.toUTF8String(utf8);
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
};

std::mutex g_normalizers_mutex;
std::unordered_map<std::string, std::unique_ptr<NativeTnNormalizer>> g_normalizers;

NativeTnNormalizer& GetNormalizer(const std::string& rules_root, const std::string& lang) {
    const std::string key = rules_root + "\n" + lang;
    std::lock_guard<std::mutex> lock(g_normalizers_mutex);
    auto& cached = g_normalizers[key];
    if (!cached) {
        cached = std::make_unique<NativeTnNormalizer>(rules_root, lang);
    }
    return *cached;
}

void ClearNormalizers(const std::string& rules_root) {
    const std::string prefix = rules_root + "\n";
    std::lock_guard<std::mutex> lock(g_normalizers_mutex);
    for (auto it = g_normalizers.begin(); it != g_normalizers.end();) {
        if (it->first.rfind(prefix, 0) == 0) {
            it = g_normalizers.erase(it);
        } else {
            ++it;
        }
    }
}

}  // namespace

extern "C" JNIEXPORT jstring JNICALL
Java_com_lits_tts_sdk_internal_NativeTnNormalizer_normalizeNative(
    JNIEnv* env,
    jobject /* thiz */,
    jstring rules_root,
    jstring lang,
    jstring text) {
    try {
        const std::string rules_root_utf8 = ToUtf8(env, rules_root);
        const std::string lang_utf8 = ToUtf8(env, lang);
        const std::string text_utf8 = ToUtf8(env, text);
        if (text_utf8.empty()) {
            return ToJString(env, text_utf8);
        }
        const std::string normalized = GetNormalizer(rules_root_utf8, lang_utf8).Normalize(text_utf8);
        return ToJString(env, normalized.empty() ? text_utf8 : normalized);
    } catch (const std::exception& error) {
        __android_log_print(ANDROID_LOG_ERROR, kLogTag, "normalize failed: %s", error.what());
        jclass exception_class = env->FindClass("java/lang/IllegalStateException");
        if (exception_class != nullptr) {
            env->ThrowNew(exception_class, error.what());
        }
        return nullptr;
    } catch (...) {
        __android_log_print(ANDROID_LOG_ERROR, kLogTag, "normalize failed: unknown error");
        jclass exception_class = env->FindClass("java/lang/IllegalStateException");
        if (exception_class != nullptr) {
            env->ThrowNew(exception_class, "native TN normalize failed");
        }
        return nullptr;
    }
}

extern "C" JNIEXPORT void JNICALL
Java_com_lits_tts_sdk_internal_NativeTnNormalizer_clearCacheNative(
    JNIEnv* env,
    jobject /* thiz */,
    jstring rules_root) {
    try {
        ClearNormalizers(ToUtf8(env, rules_root));
    } catch (const std::exception& error) {
        __android_log_print(ANDROID_LOG_ERROR, kLogTag, "clear cache failed: %s", error.what());
    } catch (...) {
        __android_log_print(ANDROID_LOG_ERROR, kLogTag, "clear cache failed: unknown error");
    }
}
