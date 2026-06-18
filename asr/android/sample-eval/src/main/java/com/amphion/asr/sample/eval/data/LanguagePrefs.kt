package com.amphion.asr.sample.eval.data

import android.content.Context
import android.content.SharedPreferences
import com.amphion.asr.AsrLanguage

/**
 * 持久化「上次录音用的语言」。
 *
 * 0.2.0 起 SDK 把全部语言模型打进 AAR；评测版只需要在 [AsrLanguage.ZH_EN] 与
 * [AsrLanguage.YUE_EN] 之间切换，不再有 modelId / version 维度。
 *
 * 找不到（用户首次启动）时调用方应回退到默认选择策略（按 SentenceManifest.lang 推导）。
 *
 * 不放到 [TesterPrefs]：tester 是身份，language 是工具偏好；混在一起会让"清除测试员身份时
 * 顺便清除引擎偏好"，这通常不是想要的。
 */
class LanguagePrefs(ctx: Context) {

    private val sp: SharedPreferences =
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    fun lastLanguage(): AsrLanguage? {
        val raw = sp.getString(KEY_LANGUAGE, null)?.takeIf { it.isNotBlank() } ?: return null
        return runCatching { AsrLanguage.valueOf(raw) }.getOrNull()
    }

    fun set(lang: AsrLanguage) {
        sp.edit().putString(KEY_LANGUAGE, lang.name).apply()
    }

    fun clear() {
        sp.edit().remove(KEY_LANGUAGE).apply()
    }

    companion object {
        // 沿用 0.1.x 的 SP 名字以便复用磁盘空间；KEY 不同，旧记录会被忽略
        private const val NAME = "amphion_eval_engine"
        private const val KEY_LANGUAGE = "language"
    }
}
