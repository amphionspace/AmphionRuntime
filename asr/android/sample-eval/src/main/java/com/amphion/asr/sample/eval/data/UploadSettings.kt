package com.amphion.asr.sample.eval.data

import android.content.Context
import android.content.SharedPreferences

/**
 * 上传链路配置（服务器 URL / Bearer token / 自动上传开关）。
 *
 * 安全说明：
 * - token 仅存在本机 SharedPreferences（私有目录，root 才能读）
 * - 不通过 logcat 打印；HttpUploader 把请求时也 mask 掉 token
 * - 用户切换测试员 / 清理时不会自动清 token（token 与 tester 绑定但生命周期不同；
 *   实际由 EvalActivity 的 Toolbar 提供独立的"重置服务器配置"入口）
 */
class UploadSettings(ctx: Context) {

    private val sp: SharedPreferences =
        ctx.applicationContext.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)

    fun isConfigured(): Boolean =
        !serverUrl().isNullOrBlank() && !bearerToken().isNullOrBlank()

    fun serverUrl(): String? = sp.getString(KEY_SERVER_URL, null)

    fun bearerToken(): String? = sp.getString(KEY_BEARER_TOKEN, null)

    /** 自动上传默认开。关闭后录音保存不触发上传，只能由「立即同步」手动触发。 */
    fun autoUploadEnabled(): Boolean = sp.getBoolean(KEY_AUTO_UPLOAD, true)

    fun update(serverUrl: String?, bearerToken: String?, autoUpload: Boolean) {
        sp.edit()
            .putString(KEY_SERVER_URL, serverUrl?.trim()?.trimEnd('/'))
            .putString(KEY_BEARER_TOKEN, bearerToken?.trim())
            .putBoolean(KEY_AUTO_UPLOAD, autoUpload)
            .apply()
    }

    fun setAutoUpload(enabled: Boolean) {
        sp.edit().putBoolean(KEY_AUTO_UPLOAD, enabled).apply()
    }

    fun clear() {
        sp.edit().clear().apply()
    }

    companion object {
        private const val PREF_NAME = "amphion_eval_upload"
        private const val KEY_SERVER_URL = "server_url"
        private const val KEY_BEARER_TOKEN = "bearer_token"
        private const val KEY_AUTO_UPLOAD = "auto_upload"
    }
}
