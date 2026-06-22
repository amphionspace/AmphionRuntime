package com.lits.tts.sdk

import com.lits.tts.sdk.internal.EngineRegistry
import java.util.concurrent.Executors

object TtsErrorCode {
    const val TEXT_LENGTH_INVALID = 1002300001
    const val LANGUAGE_UNSUPPORTED = 1002300002
    const val VOICE_UNSUPPORTED = 1002300003
    const val CREATE_ENGINE_FAILED = 1002300005
    const val ENGINE_LIMIT_REACHED = 1002300006
    const val ENGINE_NOT_INITIALIZED = 1002300007
    const val ENGINE_DESTROYED = 1002300008
    const val INTERNAL_SERVICE_ERROR = 1002300009
    const val QUEUE_FULL = 1002300010
    const val RUNTIME_EXCEPTION = 1002300011
}

class TextToSpeechException(
    val errorCode: Int,
    override val message: String,
) : RuntimeException(message)

interface Callback<T> {
    fun onSuccess(result: T)
    fun onError(errorCode: Int, errorMessage: String)
}

enum class RunMode {
    OFFLINE,
    ONLINE,
}

enum class PlayType {
    SYNTHESIZE_ONLY,
    SYNTHESIZE_AND_PLAY,
}

enum class QueueMode {
    QUEUE,
    PREEMPT,
}

enum class CompleteType {
    SYNTHESIS_COMPLETE,
    PLAYBACK_COMPLETE,
}

enum class StopType {
    STOP_ALL,
    STOP_PLAYBACK_ONLY,
}

data class CreateEngineParams @JvmOverloads constructor(
    val language: String,
    val mode: RunMode,
    val voiceId: String,
    val locate: String = "CN",
    val engineName: String? = null,
    val extraParams: Map<String, Any?> = emptyMap(),
    val modelLoadOnCreate: Boolean = true,
)

data class VoiceQuery @JvmOverloads constructor(
    val requestId: String,
    val mode: RunMode,
    val language: String? = null,
    val extraParams: Map<String, Any?> = emptyMap(),
)

data class VoiceInfo @JvmOverloads constructor(
    val language: String,
    val voiceId: String,
    val gender: String,
    val description: String? = null,
)

data class SpeakParams @JvmOverloads constructor(
    val requestId: String,
    val speed: Float = 1.0f,
    val volume: Float = 1.0f,
    val pitch: Float = 1.0f,
    val languageContext: String = "zh-CN",
    val audioType: String = "pcm",
    val playType: PlayType = PlayType.SYNTHESIZE_AND_PLAY,
    val soundChannel: Int? = null,
    val queueMode: QueueMode = QueueMode.QUEUE,
    val extraParams: Map<String, Any?> = emptyMap(),
)

data class StartResponse @JvmOverloads constructor(
    val audioType: String = "pcm",
    val sampleRate: Int = 16000,
    val sampleBit: Int = 16,
    val audioChannel: Int = 1,
    val compressRate: Int = 0,
    val isStreaming: Boolean = false,
    val dataPath: String = "buffered_pcm",
    val modelSource: String = "unknown",
    val modelInfo: String = "",
    val loadProfileInfo: String = "",
)

data class SynthesisResponse @JvmOverloads constructor(
    val sequence: Int,
    val audioType: String = "pcm",
    val isStreaming: Boolean = false,
    val chunkSource: String = "buffered_pcm",
)

data class CompleteResponse @JvmOverloads constructor(
    val type: CompleteType,
    val message: String,
    val firstPacketMs: Long = -1L,
    val synthesisMs: Long = -1L,
    val audioDurationMs: Long = -1L,
    val rtf: Double = -1.0,
    val profilingInfo: String = "",
)

data class StopResponse(
    val type: StopType,
    val message: String,
)

interface SpeakListener {
    fun onStart(requestId: String, response: StartResponse) = Unit
    fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) = Unit
    fun onComplete(requestId: String, response: CompleteResponse) = Unit
    fun onStop(requestId: String, response: StopResponse) = Unit
    fun onError(requestId: String, errorCode: Int, errorMessage: String) = Unit
}

interface TextToSpeechEngine {
    fun setListener(listener: SpeakListener)
    fun speak(text: String, params: SpeakParams)
    fun stop()
    fun isBusy(): Boolean
    fun shutdown()
}

object TextToSpeechSdk {
    @Volatile
    private var workPath: String? = null
    private val callbackExecutor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "lits-tts-callback").apply { isDaemon = true }
    }

    @JvmStatic
    fun setWorkPath(workPath: String) {
        require(workPath.isNotBlank()) { "workPath must not be blank" }
        if (EngineRegistry.hasActiveEngines()) {
            throw TextToSpeechException(
                TtsErrorCode.INTERNAL_SERVICE_ERROR,
                "setWorkPath must be called before createEngine",
            )
        }
        this.workPath = workPath
    }

    @JvmStatic
    @Throws(TextToSpeechException::class)
    fun createEngine(params: CreateEngineParams): TextToSpeechEngine {
        return EngineRegistry.createEngine(params, workPath)
    }

    @JvmStatic
    fun createEngine(params: CreateEngineParams, callback: Callback<TextToSpeechEngine>) {
        callbackExecutor.execute {
            try {
                val engine = createEngine(params)
                dispatchCallback { callback.onSuccess(engine) }
            } catch (error: TextToSpeechException) {
                dispatchCallback { callback.onError(error.errorCode, error.message) }
            } catch (error: RuntimeException) {
                dispatchCallback {
                    callback.onError(TtsErrorCode.CREATE_ENGINE_FAILED, error.message ?: "create engine failed")
                }
            }
        }
    }

    @JvmStatic
    @Throws(TextToSpeechException::class)
    fun listVoices(params: VoiceQuery): List<VoiceInfo> {
        return EngineRegistry.listVoices(params)
    }

    @JvmStatic
    fun listVoices(params: VoiceQuery, callback: Callback<List<VoiceInfo>>) {
        callbackExecutor.execute {
            try {
                val voices = listVoices(params)
                dispatchCallback { callback.onSuccess(voices) }
            } catch (error: TextToSpeechException) {
                dispatchCallback { callback.onError(error.errorCode, error.message) }
            } catch (error: RuntimeException) {
                dispatchCallback {
                    callback.onError(TtsErrorCode.INTERNAL_SERVICE_ERROR, error.message ?: "list voices failed")
                }
            }
        }
    }

    private fun dispatchCallback(block: () -> Unit) {
        try {
            val looper = android.os.Looper.getMainLooper()
            val posted = android.os.Handler(looper).post { block() }
            if (!posted) block()
        } catch (_: Throwable) {
            block()
        }
    }
}
