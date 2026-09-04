package com.amphion.dingqiao

/**
 * 音频格式配置。
 *
 * 当前实现仅支持 PCM 16 kHz / 16 bit / 单声道。
 */
data class AudioInfo(
    val audioType: String = "pcm",
    val sampleRate: Int = 16000,
    val sampleBit: Int = 16,
    val soundChannel: Int = 1,
) {
    fun validate() {
        require(audioType == "pcm") { "audioType must be pcm" }
        require(sampleRate == 16000) { "sampleRate must be 16000" }
        require(sampleBit == 16) { "sampleBit must be 16" }
        require(soundChannel == 1) { "soundChannel must be 1" }
    }
}

/** 引擎初始化配置。 */
data class CreateEngineParams(
    val language: String = "zh-CN",
    val online: Int = DingqiaoOnlineMode.OFFLINE,
    val extraParams: Map<String, Any> = emptyMap(),
)

/** 启动识别会话配置。 */
data class StartParams(
    val sessionId: String = "",
    val audioInfo: AudioInfo = AudioInfo(),
    val extraParams: Map<String, Any> = emptyMap(),
    val speakerDiarization: SpeakerDiarizationConfig? = null,
)

/** Offline speaker diarization configuration. */
data class SpeakerDiarizationConfig(
    val maxSpeakers: Int = 4,
)

/** 识别结果。 */
data class SpeechRecognitionResult(
    val isFinal: Boolean = false,
    val isLast: Boolean = false,
    val result: String = "",
    val beginTime: Int? = null,
    val endTime: Int? = null,
    val speakerSimilarity: Float? = null,
    val targetSpeakerEnhancementApplied: Boolean? = null,
    val utteranceId: String? = null,
    val speakerIndex: Int = -1,
    val secondarySpeakerIndexes: List<Int> = emptyList(),
    val speakerConfidence: Float = 0f,
)

data class SpeakerDiarizationUpdate(
    val utteranceId: String = "",
    val revision: Int = 0,
    val speakerIndex: Int = -1,
    val secondarySpeakerIndexes: List<Int> = emptyList(),
    val beginTime: Int = 0,
    val endTime: Int = 0,
    val confidence: Float = 0f,
)

data class DiarizedUtterance(
    val utteranceId: String = "",
    val rawText: String = "",
    val text: String = "",
    val beginTime: Int = 0,
    val endTime: Int = 0,
    val speakerIndex: Int = -1,
    val secondarySpeakerIndexes: List<Int> = emptyList(),
    val confidence: Float = 0f,
    val overlap: Boolean = false,
    val sourceUtteranceId: String = utteranceId,
)

data class SpeakerTurn(
    val beginTime: Int = 0,
    val endTime: Int = 0,
    val speakerIndex: Int = -1,
    val secondarySpeakerIndexes: List<Int> = emptyList(),
    val confidence: Float = 0f,
    val overlap: Boolean = false,
)

enum class SpeakerDiarizationDegradedReason {
    NONE,
    INFERENCE_UNAVAILABLE,
    MODEL_UNAVAILABLE,
    INFERENCE_TIMEOUT,
    FINISH_TIMEOUT,
    STORAGE_UNAVAILABLE,
    SPEAKER_LIMIT_EXCEEDED,
}

data class SpeakerDiarizationResult(
    val utterances: List<DiarizedUtterance> = emptyList(),
    val speakerTurns: List<SpeakerTurn> = emptyList(),
    val speakerCount: Int = 0,
    val degraded: Boolean = false,
    val degradedReason: SpeakerDiarizationDegradedReason = SpeakerDiarizationDegradedReason.NONE,
    val degradedMessage: String? = null,
    val inferenceMs: Long = 0,
    val rtf: Float = 0f,
    val windowIndex: Int = 0,
    val windowBeginTime: Int = 0,
    val windowEndTime: Int = 0,
    val isSessionFinal: Boolean = false,
)

/** 声纹注册请求。 */
data class VoiceprintRegisterParams(
    val samplePaths: List<String> = emptyList(),
    val audioInfo: AudioInfo = AudioInfo(),
    /** Reserved for HarmonyOS source compatibility; registration still generates a secure ID. */
    val voiceprintId: String = "",
)

/** 声纹注册结果。 */
data class VoiceprintRegisterResult(
    val voiceprintId: Map<String, String> = emptyMap(),
    val status: Int = 0,
    val message: String = "",
)

/** License 信息。 */
data class LicenseInfo(
    val status: Int = 0,
    val expireTime: Long = -1,
    val remainingDays: Int = -1,
    val authorizedFeatures: List<String> = emptyList(),
)

/** License 激活结果。 */
data class LicenseActivationResult(
    val errorCode: Int = 0,
    val errorMessage: String = "",
    val remainingDays: Int? = null,
    val authorizedFeatures: List<String>? = null,
)

/** @deprecated Diagnostics behavior is selected by the AAR build variant. */
@Deprecated("Diagnostics behavior is selected by the AAR build variant")
object DiagnosticMode {
    const val BASIC: String = "BASIC"
    const val CUSTOMER_SUPPORT: String = "CUSTOMER_SUPPORT"
    const val FAILURE_ONLY: String = "FAILURE_ONLY"
}

/**
 * @deprecated Kept for source compatibility. Runtime options cannot enable capture in a normal
 * debug/release AAR; use the dedicated diagnostics artifact.
 */
@Deprecated("Use the dedicated diagnostics artifact")
data class DiagnosticOptions(
    val enabled: Boolean = false,
    val mode: String = DiagnosticMode.BASIC,
    val captureAudio: Boolean = false,
    val includeRecognitionText: Boolean = false,
    val maxSessionAudioSec: Int = 300,
    val failureRingAudioSec: Int = 20,
    val maxSessionEvents: Int = 512,
    val maxDirectoryMb: Int = 200,
    val maxRetainedRuns: Int = 3,
) {
    companion object {
        @JvmStatic
        fun customerSupport(): DiagnosticOptions = DiagnosticOptions(
            enabled = true,
            mode = DiagnosticMode.CUSTOMER_SUPPORT,
        )

        @JvmStatic
        fun failureOnly(): DiagnosticOptions = DiagnosticOptions(
            enabled = true,
            mode = DiagnosticMode.FAILURE_ONLY,
        )
    }
}

/** Diagnostics export callback. Export is asynchronous. */
interface DiagnosticExportCallback {
    fun onSuccess(path: String)
    fun onError(errorCode: Int, errorMessage: String)
}

/** 异步创建引擎回调。 */
interface CreateEngineCallback {
    fun onSuccess(engine: SpeechRecognitionEngine) {
        onResult(engine)
    }

    /**
     * 旧版 Android 回调名。新代码应实现 [onSuccess]；保留默认实现以维持二进制源代码兼容。
     */
    @Deprecated("Use onSuccess(engine)")
    fun onResult(engine: SpeechRecognitionEngine) {}

    fun onError(errorCode: Int, errorMessage: String) {}
}

/** License 异步激活回调。 */
interface LicenseActivationCallback {
    fun onResult(result: LicenseActivationResult)
    fun onError(errorCode: Int, errorMessage: String) {}
}

/** Runtime 准备回调；[onReady] 表示默认中英识别模型已在 SDK 内部就绪。 */
interface PrepareRuntimeCallback {
    fun onReady()
    fun onError(errorCode: Int, errorMessage: String) {}
}

/** 声纹注册异步回调。注册会加载 ~38MB 声纹模型并计算 embedding，务必走异步重载，勿在 UI 线程同步调用。 */
interface VoiceprintRegisterCallback {
    fun onResult(result: VoiceprintRegisterResult)
    fun onError(errorCode: Int, errorMessage: String) {}
}

/** 识别过程回调，与鼎桥 [RecognitionListener] 对齐。 */
interface RecognitionListener {
    fun onStart(sessionId: String, eventMessage: String) {}
    fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) {}
    fun onResult(sessionId: String, result: SpeechRecognitionResult) {}
    fun onSpeakerDiarizationUpdate(sessionId: String, update: SpeakerDiarizationUpdate) {}
    fun onSpeakerDiarizationResult(sessionId: String, result: SpeakerDiarizationResult) {}
    fun onComplete(sessionId: String, eventMessage: String) {}
    fun onError(sessionId: String, errorCode: Int, errorMessage: String) {}
}

/** 语音识别引擎实例。 */
interface SpeechRecognitionEngine {
    fun setListener(listener: RecognitionListener?)
    fun startListening(params: StartParams)
    fun writeAudio(sessionId: String, audio: ByteArray)
    fun finish(sessionId: String)
    fun cancel(sessionId: String)
    fun setSpeakerVadEnabled(enabled: Boolean) {}
    fun isBusy(): Boolean
    fun shutdown()
}
