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
    val language: String,
    val online: Int = DingqiaoOnlineMode.OFFLINE,
    val extraParams: Map<String, Any> = emptyMap(),
)

/** 启动识别会话配置。 */
data class StartParams(
    val sessionId: String,
    val audioInfo: AudioInfo,
    val extraParams: Map<String, Any> = emptyMap(),
)

/** 识别结果。 */
data class SpeechRecognitionResult(
    val isFinal: Boolean,
    val isLast: Boolean,
    val result: String,
    val beginTime: Int? = null,
    val endTime: Int? = null,
    val speakerSimilarity: Float? = null,
)

/** 声纹注册请求。 */
data class VoiceprintRegisterParams(
    val samplePaths: List<String>,
    val audioInfo: AudioInfo,
)

/** 声纹注册结果。 */
data class VoiceprintRegisterResult(
    val voiceprintId: Map<String, String>,
    val status: Int,
)

/** License 信息。 */
data class LicenseInfo(
    val status: Int,
    val expireTime: Long,
    val remainingDays: Int,
    val authorizedFeatures: List<String>,
)

/** License 激活结果。 */
data class LicenseActivationResult(
    val errorCode: Int,
    val errorMessage: String? = null,
    val remainingDays: Int? = null,
    val authorizedFeatures: List<String>? = null,
)

/** 异步创建引擎回调。 */
interface CreateEngineCallback {
    fun onResult(engine: SpeechRecognitionEngine)
    fun onError(errorCode: Int, errorMessage: String) {}
}

/** License 异步激活回调。 */
interface LicenseActivationCallback {
    fun onResult(result: LicenseActivationResult)
    fun onError(errorCode: Int, errorMessage: String) {}
}

/** 声纹注册异步回调。注册会加载 ~38MB 声纹模型并计算 embedding，务必走异步重载，勿在 UI 线程同步调用。 */
interface VoiceprintRegisterCallback {
    fun onResult(result: VoiceprintRegisterResult)
    fun onError(errorCode: Int, errorMessage: String) {}
}

/** 识别过程回调，与鼎桥 [RecognitionListener] 对齐。 */
interface RecognitionListener {
    fun onStart(sessionId: String, eventMessage: String)
    fun onEvent(sessionId: String, eventCode: Int, eventMessage: String)
    fun onResult(sessionId: String, result: SpeechRecognitionResult)
    fun onComplete(sessionId: String, eventMessage: String)
    fun onError(sessionId: String, errorCode: Int, errorMessage: String)
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
