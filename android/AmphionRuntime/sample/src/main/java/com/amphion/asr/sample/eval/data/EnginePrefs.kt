package com.amphion.asr.sample.eval.data

import android.content.Context
import android.content.SharedPreferences

/**
 * 持久化「上次录音用的引擎」。
 *
 * 设计要点：
 * - 用 modelId + version 联合唯一识别一份本地模型（与 [com.amphion.asr.LocalModel] 对齐）
 * - 不持久化 LocalModel 对象本身：dir 是绝对路径，跨重启 / 跨设备会变；只存逻辑标识
 * - 找不到时（用户删了模型 / 升级了版本）调用方应回退到默认选择策略
 *
 * 不放到 [TesterPrefs]：tester 是身份，engine 是工具偏好；混在一起会让"清除测试员身份时
 * 顺便清除引擎偏好"，这通常不是想要的。
 */
class EnginePrefs(ctx: Context) {

    private val sp: SharedPreferences =
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    fun lastModelId(): String? = sp.getString(KEY_MODEL_ID, null)?.takeIf { it.isNotBlank() }
    fun lastVersion(): String? = sp.getString(KEY_VERSION, null)?.takeIf { it.isNotBlank() }

    fun set(modelId: String, version: String) {
        sp.edit().putString(KEY_MODEL_ID, modelId).putString(KEY_VERSION, version).apply()
    }

    fun clear() {
        sp.edit().remove(KEY_MODEL_ID).remove(KEY_VERSION).apply()
    }

    companion object {
        private const val NAME = "amphion_eval_engine"
        private const val KEY_MODEL_ID = "model_id"
        private const val KEY_VERSION = "version"
    }
}
