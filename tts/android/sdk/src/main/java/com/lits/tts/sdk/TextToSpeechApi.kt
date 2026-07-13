package com.lits.tts.sdk

import android.content.Context
import com.lits.tts.sdk.internal.AndroidAppContext
import com.lits.tts.sdk.internal.DeviceLicenseFingerprint
import com.lits.tts.sdk.internal.EngineRegistry
import com.lits.tts.sdk.internal.LicenseGuard
import java.io.File
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone
import java.util.concurrent.Executors

object TtsErrorCode {
    const val OK = 0

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
    const val LICENSE_MISSING = 1002300012
    const val LICENSE_MALFORMED = 1002300013
    const val LICENSE_SIGNATURE_INVALID = 1002300014
    const val LICENSE_APP_MISMATCH = 1002300015
    const val LICENSE_CERT_MISMATCH = 1002300016
    const val LICENSE_EXPIRED = 1002300017
    const val LICENSE_DEVICE_MISMATCH = 1002300018
    const val LICENSE_SDK_MAJOR_MISMATCH = 1002300019
    const val LICENSE_MAINTENANCE_EXPIRED = 1002300020
    const val LICENSE_FEATURE_MISSING = 1002300021
    const val LICENSE_NOT_SET = 1002300034
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

data class TtsStreamingConfig @JvmOverloads constructor(
    val chunkSize: Int? = null,
    val firstChunkSize: Int? = null,
    val pcmQueueCapacity: Int? = null,
)

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
    val streamingConfig: TtsStreamingConfig? = null,
)

data class StartResponse @JvmOverloads constructor(
    val audioType: String = "pcm",
    val sampleRate: Int = 24000,
    val sampleBit: Int = 16,
    val audioChannel: Int = 1,
    val compressRate: Int = 0,
    val isStreaming: Boolean = false,
    val dataPath: String = "buffered_pcm",
    val modelSource: String = "unknown",
    val modelInfo: String = "",
    val loadProfileInfo: String = "",
    val streamingChunkSize: Int = -1,
    val pcmQueueCapacity: Int = -1,
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
    val playbackStartMs: Long = -1L,
)

data class StopResponse(
    val type: StopType,
    val message: String,
)

interface SpeakListener {
    fun onStart(requestId: String, response: StartResponse) = Unit
    fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) = Unit
    /** Called when the first PCM bytes are written to the internal AudioTrack. */
    fun onPlaybackStart(requestId: String, elapsedMs: Long) = Unit
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

data class LicenseInfo(
    val status: Int,
    val expireTime: Long,
    val remainingDays: Int,
    val authorizedFeatures: List<String>,
)

data class LicenseActivationResult @JvmOverloads constructor(
    val errorCode: Int,
    val errorMessage: String? = null,
    val remainingDays: Int = -1,
    val authorizedFeatures: List<String> = emptyList(),
)

object TextToSpeechSdk {
    @Volatile
    private var workPath: String? = null
    private val callbackExecutor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "lits-tts-callback").apply { isDaemon = true }
    }

    @JvmStatic
    @JvmOverloads
    @Throws(TextToSpeechException::class)
    fun init(context: Context, options: TtsLicenseOptions = TtsLicenseOptions()) {
        LicenseGuard.configureAndVerify(context, options)
    }

    /**
     * 设置 License 文件路径，异步激活并校验。
     *
     * 与 ASR 抽象接口保持一致；应在 [createEngine] 前调用。若已设置过 License，再次调用将覆盖。
     */
    @JvmStatic
    fun setLicense(licensePath: String, callback: Callback<LicenseActivationResult>) {
        callbackExecutor.execute {
            val ctx = AndroidAppContext.tryGet()
            if (ctx == null) {
                dispatchCallback {
                    callback.onError(
                        TtsErrorCode.INTERNAL_SERVICE_ERROR,
                        "ApplicationContext unavailable for license activation",
                    )
                }
                return@execute
            }
            val licenseText = runCatching { File(licensePath).readText(Charsets.UTF_8) }.getOrElse { error ->
                dispatchCallback {
                    callback.onError(
                        TtsErrorCode.LICENSE_MISSING,
                        "License file does not exist or cannot be read: ${error.message}",
                    )
                }
                return@execute
            }
            runCatching {
                init(
                    ctx,
                    TtsLicenseOptions(
                        license = licenseText,
                        licenseAssetName = null,
                    ),
                )
                val info = getLicenseInfo()
                LicenseActivationResult(
                    errorCode = TtsErrorCode.OK,
                    errorMessage = null,
                    remainingDays = info.remainingDays,
                    authorizedFeatures = info.authorizedFeatures,
                )
            }.onSuccess { result ->
                dispatchCallback { callback.onSuccess(result) }
            }.onFailure { error ->
                val code = (error as? TextToSpeechException)?.errorCode ?: TtsErrorCode.INTERNAL_SERVICE_ERROR
                dispatchCallback { callback.onError(code, error.message ?: "license activation failed") }
            }
        }
    }

    @JvmStatic
    fun licenseStatus(): TtsLicenseStatus = LicenseGuard.status()

    /**
     * 查询当前 License 状态及授权信息。
     *
     * status: 0=有效；1=已过期；2=未激活；3=设备不匹配或其他无效状态。
     */
    @JvmStatic
    fun getLicenseInfo(): LicenseInfo {
        val current = licenseStatus()
        if (current.state == TtsLicenseStatus.State.NOT_INITIALIZED) {
            throw TextToSpeechException(TtsErrorCode.LICENSE_NOT_SET, "License has not been set")
        }
        return LicenseInfo(
            status = when {
                current.valid -> 0
                current.errorCode == TtsErrorCode.LICENSE_EXPIRED -> 1
                current.state == TtsLicenseStatus.State.NOT_INITIALIZED -> 2
                else -> 3
            },
            expireTime = expireTimeMillis(current.expiresAt),
            remainingDays = remainingDays(current.expiresAt),
            authorizedFeatures = current.features.map { it.lowercase(Locale.ROOT) },
        )
    }

    /**
     * 设备 SN 授权哈希，用于申请设备白名单 `.lic`（`authorizedDeviceHashes` 字段）。
     *
     * 算法：SHA-256(normalizedSn + deviceIdSaltId)，大写 hex、无冒号。
     */
    @JvmStatic
    fun deviceLicenseFingerprint(deviceSerial: String, deviceIdSaltId: String): String =
        DeviceLicenseFingerprint.computeFromSerial(deviceSerial, deviceIdSaltId)

    @JvmStatic
    fun deviceLicenseFingerprint(context: Context): String {
        val ctx = context.applicationContext ?: context
        return DeviceLicenseFingerprint.compute(ctx)
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

    private fun expireTimeMillis(expiresAt: String): Long {
        if (expiresAt.isBlank()) return -1L
        return parseDateUtcMillis(expiresAt) ?: -1L
    }

    private fun remainingDays(expiresAt: String): Int {
        if (expiresAt.isBlank()) return -1
        val expires = parseDateUtcMillis(expiresAt) ?: return -1
        val remainingMs = (expires + DAY_MS - System.currentTimeMillis()).coerceAtLeast(0L)
        return (remainingMs / DAY_MS).toInt()
    }

    private fun parseDateUtcMillis(date: String): Long? = try {
        SimpleDateFormat("yyyy-MM-dd", Locale.ROOT).apply {
            timeZone = TimeZone.getTimeZone("UTC")
            isLenient = false
        }.parse(date)?.time
    } catch (_: Throwable) {
        null
    }

    private const val DAY_MS = 24L * 60 * 60 * 1000
}
