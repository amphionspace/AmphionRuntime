package com.amphion.asr.sample.eval.model

import org.json.JSONObject

/**
 * 一条录音的全部元信息，与 audio.wav 同目录的 meta.json 对应。
 *
 * 关键不变量：
 * - [finalized] = true 才视为有效样本；后台 eval_wer.py 应跳过 finalized=false 的目录
 * - [referenceText] 必须与 [sentenceId] 同时存在；后台优先按 referenceText 字面量算 WER，
 *   sentenceId 仅用于聚合，避免测试集版本漂移把老数据废掉
 * - [upload] 的 state 是单一事实源；UploadScanner 按此字段决定是否触发上传
 *
 * schemaVersion 升级流程：
 * 1. 改 docs/eval/SERVER_SPEC.md 与 docs/eval/SCHEMA.md
 * 2. bump [CURRENT_SCHEMA_VERSION] 并加序列化兼容
 * 3. 客户端发布
 * 4. 服务端跟进
 */
data class RecordingMeta(
    val schemaVersion: Int = CURRENT_SCHEMA_VERSION,
    val finalized: Boolean,
    val recordingId: String,
    val attemptIndex: Int,
    val sentenceId: String,
    val categoryId: String,
    val referenceText: String,
    val testerId: String,
    val testerNickname: String,
    val device: DeviceMeta,
    val appVersion: String,
    val sdkVersion: String,
    val modelId: String?,
    val modelVersion: String?,
    val recordedAt: String,
    val durationMs: Long,
    val sampleRate: Int,
    val gainDb: Float,
    val audioSource: String,
    val env: EnvMeta,
    val onDeviceHypothesis: String?,
    val onDeviceWerEstimate: Double?,
    /**
     * 端侧 SDK metrics（来自 [com.amphion.asr.AmphionMetrics] kind=UTTERANCE）。
     *
     * 全部可选；引擎不可用 / 没拿到 metrics 时为 null。本地 schema_version=1 阶段，
     * 这些字段对老服务端透明（被 ignore）；server schema 升 v2 时再正式纳入字段表。
     */
    val onDeviceUtteranceE2eMs: Long? = null,
    val onDeviceFirstPartialMs: Long? = null,
    val onDeviceRtf: Float? = null,
    val onDeviceNativeRssMb: Int? = null,
    val upload: UploadMeta = UploadMeta(),
) {

    fun toJson(): JSONObject = JSONObject().apply {
        put("schema_version", schemaVersion)
        put("finalized", finalized)
        put("recording_id", recordingId)
        put("attempt_index", attemptIndex)
        put("sentence_id", sentenceId)
        put("category_id", categoryId)
        put("reference_text", referenceText)
        put("tester_id", testerId)
        put("tester_nickname", testerNickname)
        put("device", device.toJson())
        put("app_version", appVersion)
        put("sdk_version", sdkVersion)
        put("model_id", modelId ?: JSONObject.NULL)
        put("model_version", modelVersion ?: JSONObject.NULL)
        put("recorded_at", recordedAt)
        put("duration_ms", durationMs)
        put("sample_rate", sampleRate)
        put("gain_db", gainDb.toDouble())
        put("audio_source", audioSource)
        put("env", env.toJson())
        put("on_device_hypothesis", onDeviceHypothesis ?: JSONObject.NULL)
        put(
            "on_device_wer_estimate",
            onDeviceWerEstimate?.let { it } ?: JSONObject.NULL
        )
        // ---- SDK metrics（schema 1 之外，server ignore；future bump 后纳入） ----
        put("on_device_utterance_e2e_ms", onDeviceUtteranceE2eMs ?: JSONObject.NULL)
        put("on_device_first_partial_ms", onDeviceFirstPartialMs ?: JSONObject.NULL)
        put(
            "on_device_rtf",
            onDeviceRtf?.toDouble() ?: JSONObject.NULL,
        )
        put("on_device_native_rss_mb", onDeviceNativeRssMb ?: JSONObject.NULL)
        put("upload", upload.toJson())
    }

    fun toJsonString(): String = toJson().toString(2)

    /** 重新生成一份"copy + 改 upload 字段"的新实例。 */
    fun withUpload(upload: UploadMeta): RecordingMeta = copy(upload = upload)

    companion object {
        const val CURRENT_SCHEMA_VERSION: Int = 1

        fun fromJson(text: String): RecordingMeta = fromJson(JSONObject(text))

        fun fromJson(o: JSONObject): RecordingMeta {
            val sv = o.optInt("schema_version", 0)
            check(sv in 1..CURRENT_SCHEMA_VERSION) {
                "RecordingMeta schema_version=$sv not supported (max $CURRENT_SCHEMA_VERSION)"
            }
            return RecordingMeta(
                schemaVersion = sv,
                finalized = o.optBoolean("finalized", false),
                recordingId = o.getString("recording_id"),
                attemptIndex = o.optInt("attempt_index", 1),
                sentenceId = o.getString("sentence_id"),
                categoryId = o.optString("category_id", ""),
                referenceText = o.getString("reference_text"),
                testerId = o.getString("tester_id"),
                testerNickname = o.optString("tester_nickname", o.getString("tester_id")),
                device = DeviceMeta.fromJson(o.getJSONObject("device")),
                appVersion = o.optString("app_version", "0.0.0"),
                sdkVersion = o.optString("sdk_version", "0.0.0"),
                modelId = o.optStringOrNull("model_id"),
                modelVersion = o.optStringOrNull("model_version"),
                recordedAt = o.getString("recorded_at"),
                durationMs = o.optLong("duration_ms", 0L),
                sampleRate = o.optInt("sample_rate", 16000),
                gainDb = o.optDouble("gain_db", 0.0).toFloat(),
                audioSource = o.optString("audio_source", "VOICE_RECOGNITION"),
                env = EnvMeta.fromJson(o.optJSONObject("env") ?: JSONObject()),
                onDeviceHypothesis = o.optStringOrNull("on_device_hypothesis"),
                onDeviceWerEstimate = o.optDoubleOrNull("on_device_wer_estimate"),
                onDeviceUtteranceE2eMs = o.optLongOrNull("on_device_utterance_e2e_ms"),
                onDeviceFirstPartialMs = o.optLongOrNull("on_device_first_partial_ms"),
                onDeviceRtf = o.optDoubleOrNull("on_device_rtf")?.toFloat(),
                onDeviceNativeRssMb = o.optIntOrNull("on_device_native_rss_mb"),
                upload = UploadMeta.fromJson(o.optJSONObject("upload") ?: JSONObject()),
            )
        }
    }
}

/** 设备硬件 / 系统侧信息，全部 SDK API 自动采集，无需测试员填。 */
data class DeviceMeta(
    val model: String,
    val manufacturer: String,
    val androidSdk: Int,
    val abi: String,
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("model", model)
        put("manufacturer", manufacturer)
        put("android_sdk", androidSdk)
        put("abi", abi)
    }

    companion object {
        fun fromJson(o: JSONObject): DeviceMeta = DeviceMeta(
            model = o.optString("model", "unknown"),
            manufacturer = o.optString("manufacturer", "unknown"),
            androidSdk = o.optInt("android_sdk", 0),
            abi = o.optString("abi", "unknown"),
        )
    }
}

/** 由测试员填写的环境元信息。`noiseLevel` 用 NoiseLevel 枚举的字面量，避免 i18n 抖动。 */
data class EnvMeta(
    val location: String,
    val noiseLevel: String,
    val noiseLevelDbEstimate: Double?,
    val notes: String,
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("location", location)
        put("noise_level", noiseLevel)
        put("noise_level_db_estimate", noiseLevelDbEstimate ?: JSONObject.NULL)
        put("notes", notes)
    }

    companion object {
        val EMPTY = EnvMeta(
            location = "",
            noiseLevel = NoiseLevel.UNSPECIFIED.token,
            noiseLevelDbEstimate = null,
            notes = "",
        )

        fun fromJson(o: JSONObject): EnvMeta = EnvMeta(
            location = o.optString("location", ""),
            noiseLevel = o.optString("noise_level", NoiseLevel.UNSPECIFIED.token),
            noiseLevelDbEstimate = o.optDoubleOrNull("noise_level_db_estimate"),
            notes = o.optString("notes", ""),
        )
    }
}

enum class NoiseLevel(val token: String, val displayResId: Int) {
    UNSPECIFIED("unspecified", com.amphion.asr.sample.R.string.eval_noise_unspecified),
    SILENT("silent", com.amphion.asr.sample.R.string.eval_noise_silent),
    LOW("low", com.amphion.asr.sample.R.string.eval_noise_low),
    MEDIUM("medium", com.amphion.asr.sample.R.string.eval_noise_medium),
    HIGH("high", com.amphion.asr.sample.R.string.eval_noise_high),
    VERY_HIGH("very_high", com.amphion.asr.sample.R.string.eval_noise_very_high);

    companion object {
        fun fromToken(token: String?): NoiseLevel =
            values().firstOrNull { it.token == token } ?: UNSPECIFIED
    }
}

/**
 * 单条录音的上传状态机。state 是单一事实源：
 * - PENDING：刚保存，待上传
 * - UPLOADING：HttpUploader 正在执行（应只是瞬态，不应持久化在 PENDING 之外）
 * - UPLOADED：服务端返回 200 stored/duplicate
 * - RETRY：临时失败（网络/5xx），下次扫描继续
 * - FAILED：永久失败（4xx，需要人工介入）
 */
data class UploadMeta(
    val state: String = State.PENDING,
    val uploadedAt: String? = null,
    val attempts: Int = 0,
    val lastError: String? = null,
    val lastAttemptAt: String? = null,
    val serverUrl: String? = null,
) {
    object State {
        const val PENDING = "pending"
        const val UPLOADING = "uploading"
        const val UPLOADED = "uploaded"
        const val RETRY = "retry"
        const val FAILED = "failed"
    }

    val isUploaded: Boolean get() = state == State.UPLOADED
    val isInflight: Boolean get() = state == State.UPLOADING
    val needsUpload: Boolean get() = state == State.PENDING || state == State.RETRY

    fun toJson(): JSONObject = JSONObject().apply {
        put("state", state)
        put("uploaded_at", uploadedAt ?: JSONObject.NULL)
        put("attempts", attempts)
        put("last_error", lastError ?: JSONObject.NULL)
        put("last_attempt_at", lastAttemptAt ?: JSONObject.NULL)
        put("server_url", serverUrl ?: JSONObject.NULL)
    }

    companion object {
        fun fromJson(o: JSONObject): UploadMeta = UploadMeta(
            state = o.optString("state", State.PENDING),
            uploadedAt = o.optStringOrNull("uploaded_at"),
            attempts = o.optInt("attempts", 0),
            lastError = o.optStringOrNull("last_error"),
            lastAttemptAt = o.optStringOrNull("last_attempt_at"),
            serverUrl = o.optStringOrNull("server_url"),
        )
    }
}

private fun JSONObject.optStringOrNull(key: String): String? {
    if (!has(key) || isNull(key)) return null
    val v = optString(key, "")
    return if (v.isEmpty()) null else v
}

private fun JSONObject.optDoubleOrNull(key: String): Double? {
    if (!has(key) || isNull(key)) return null
    return optDouble(key, Double.NaN).takeUnless { it.isNaN() }
}

private fun JSONObject.optLongOrNull(key: String): Long? {
    if (!has(key) || isNull(key)) return null
    return optLong(key, Long.MIN_VALUE).takeUnless { it == Long.MIN_VALUE }
}

private fun JSONObject.optIntOrNull(key: String): Int? {
    if (!has(key) || isNull(key)) return null
    return optInt(key, Int.MIN_VALUE).takeUnless { it == Int.MIN_VALUE }
}
