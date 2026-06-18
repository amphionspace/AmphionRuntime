package com.lits.tts.sdk

import android.content.Context
import com.lits.tts.sdk.internal.DeviceLicenseFingerprint
import com.lits.tts.sdk.internal.EngineRegistry
import com.lits.tts.sdk.internal.LicenseGuard
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

    // 离线 license 验签 / 绑定校验失败码（仅在 SDK 被武装、即构建期注入公钥时可能出现）。
    /** 未提供 license（[TtsLicenseOptions.license] 为空且 asset 不存在）。 */
    const val LICENSE_MISSING = 1002300012

    /** license 内容不是合法 JSON 或缺必填字段。 */
    const val LICENSE_MALFORMED = 1002300013

    /** ECDSA 验签未通过（被篡改或用了非我方签发的 license）。 */
    const val LICENSE_SIGNATURE_INVALID = 1002300014

    /** license 的 applicationId 与宿主 app packageName 不一致。 */
    const val LICENSE_APP_MISMATCH = 1002300015

    /** license 的 certSha256 与宿主 app 签名证书不一致。 */
    const val LICENSE_CERT_MISMATCH = 1002300016

    /** license 已过期（超出宽限期）。 */
    const val LICENSE_EXPIRED = 1002300017

    /** license 绑定的设备指纹与当前设备不一致（单机授权）。 */
    const val LICENSE_DEVICE_MISMATCH = 1002300018
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
    val languageContext: String = "zh-en",
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
)

data class SynthesisResponse @JvmOverloads constructor(
    val sequence: Int,
    val audioType: String = "pcm",
)

data class CompleteResponse(
    val type: CompleteType,
    val message: String,
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

    /**
     * 可选的显式 license 初始化（开发 / 内部构建下为 no-op）。
     *
     * SDK 通过内部机制自动发现 ApplicationContext 并在 [createEngine] 前懒校验一次，所以业务方
     * 即使不调用本方法也会被强制校验；提供本入口是为了：让业务方在启动时主动传入 license 文本 /
     * 调整 [TtsLicenseOptions.enforcement] / 尽早暴露授权问题。重复调用以最后一次为准。
     *
     * @param context 任意 [Context]，仅取其 ApplicationContext，不长期持有
     * @param options license 选项，详见 [TtsLicenseOptions]
     * @throws TextToSpeechException 当 SDK 被武装、校验失败且策略为
     *   [LicenseEnforcement.ENFORCE] 时抛出（errorCode 取自 [TtsErrorCode] 的 `LICENSE_*` 段）
     */
    @JvmStatic
    @JvmOverloads
    @Throws(TextToSpeechException::class)
    fun init(context: Context, options: TtsLicenseOptions = TtsLicenseOptions()) {
        LicenseGuard.configureAndVerify(context, options)
    }

    /**
     * 查询当前 license 运行状态。任何校验（[init] 或首次 [createEngine]）触发前返回
     * [TtsLicenseStatus.State.NOT_INITIALIZED]；开发 / 内部构建返回
     * [TtsLicenseStatus.State.DEV_UNLICENSED]。可用于在「关于」页展示授权客户 / 到期日 / 档位。
     */
    @JvmStatic
    fun licenseStatus(): TtsLicenseStatus = LicenseGuard.status()

    /**
     * 本机设备指纹，用于申请单机绑定的 `.lic`（`deviceSha256` 字段）。
     *
     * 无需先 [init]；在目标真机 Release 包上调用后，将返回值提供给授权签发方。
     * 算法：SHA-256("{packageName}|{ANDROID_ID}")，大写 hex、无冒号。
     */
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
}
