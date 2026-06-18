package com.amphion.asr.sample

import android.content.Context

/**
 * 云端 ASR（WebSocket `/clean-stream`）的本地配置。
 *
 * 地址按需求写死为 [WS_URL]（平台默认接入点），不暴露给用户编辑；这里只持久化
 * 「是否启用」一项，与热词 / 声纹的 prefs 风格一致（各自独立文件，互不污染）。
 */
class CloudAsrPrefs(context: Context) {

    private val sp = context.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun isEnabled(): Boolean = sp.getBoolean(KEY_ENABLED, false)

    fun setEnabled(enabled: Boolean) {
        sp.edit().putBoolean(KEY_ENABLED, enabled).apply()
    }

    companion object {
        private const val FILE = "cloud_asr_prefs"
        private const val KEY_ENABLED = "enabled"

        /** 云端流式 ASR 接入点：Amphion 开放平台「增强型流式 ASR」/clean-stream。 */
        const val WS_URL = "wss://amphion.top/asr/v1/clean-stream"

        /**
         * 平台 API Key。来源 local.properties 的 cloudAsrApiKey，经 BuildConfig 注入
         * （见 samples/public-demo/build.gradle.kts），不写进源码与仓库。鉴权走 `Authorization: Bearer`
         * （见 [CloudAsrClient]），不拼进 URL，避免 key 落到日志/状态栏。
         * 未配置时为空串：云端开关会鉴权失败并给出可读错误，端侧识别不受影响。
         */
        val API_KEY: String = BuildConfig.CLOUD_ASR_API_KEY
    }
}
