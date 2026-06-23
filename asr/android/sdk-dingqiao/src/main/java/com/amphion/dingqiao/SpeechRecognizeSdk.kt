package com.amphion.dingqiao

import android.content.Context
import com.amphion.asr.AmphionRuntime
import com.amphion.asr.AmphionLicenseStatus
import com.amphion.asr.AmphionOptions
import com.amphion.asr.AsrErrorCode
import com.amphion.asr.SpeakerEnroller
import java.io.File
import java.time.LocalDate
import java.time.ZoneOffset
import java.time.temporal.ChronoUnit
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * 鼎桥语音识别 SDK 入口，对齐 [语音识别SDK接口.md]。
 *
 * Android 平台须先调用 [init] 注入 [Context]，再 [setWorkPath]。
 */
object SpeechRecognizeSdk {

    @Volatile
    private var appContext: Context? = null

    @Volatile
    private var workPath: File? = null

    @Volatile
    private var licenseInfo: LicenseInfo? = null

    @Volatile
    private var runtimeInitialized: Boolean = false

    private val engineExecutor: ExecutorService = Executors.newCachedThreadPool { r ->
        Thread(r, "dingqiao-engine").apply { isDaemon = true }
    }

    /**
     * Android 平台初始化（须在 [createEngine] / [registerVoiceprint] 之前调用一次）。
     */
    @JvmStatic
    fun init(context: Context) {
        val ctx = context.applicationContext ?: context
        if (appContext == null) {
            synchronized(this) {
                if (appContext == null) {
                    appContext = ctx
                }
            }
        }
    }

    /**
     * 指定 SDK 工作目录（声纹、speaker 模型等）。须在 [createEngine] 之前调用。
     */
    @JvmStatic
    fun setWorkPath(path: String) {
        val dir = File(path)
        dir.mkdirs()
        require(dir.isDirectory && dir.canWrite()) { "workPath must be writable: $path" }
        workPath = dir
    }

    /**
     * 本机设备指纹，用于申请单机试用 license（无需先 [init]）。
     * 在目标真机 Release 包上获取后提供给授权签发方。
     */
    @JvmStatic
    fun deviceLicenseFingerprint(context: Context): String =
        AmphionRuntime.deviceLicenseFingerprint(context)

    /**
     * 创建识别引擎（同步）。
     */
    @JvmStatic
    fun createEngine(params: CreateEngineParams): SpeechRecognitionEngine {
        val ctx = requireContext()
        ensureRuntimeInitialized(ctx)
        val store = requireStore()
        val speakerModel = store.speakerModelPath().takeIf { it.isFile }?.absolutePath
        return DingqiaoRecognitionEngine.create(
            appContext = ctx,
            params = params,
            voiceprintStore = store,
            speakerModelPath = speakerModel,
        )
    }

    /**
     * 创建识别引擎（异步回调）。
     */
    @JvmStatic
    fun createEngine(params: CreateEngineParams, callback: CreateEngineCallback) {
        engineExecutor.execute {
            try {
                val engine = createEngine(params)
                callback.onResult(engine)
            } catch (t: Throwable) {
                val code = (t as? DingqiaoEngineException)?.errorCode
                    ?: DingqiaoErrorCode.CREATE_ENGINE_FAILED
                callback.onError(code, t.message ?: "createEngine failed")
            }
        }
    }

    /**
     * 设置 License 文件路径并异步激活。须在 [createEngine] 前调用；再次调用会覆盖当前进程内状态。
     */
    @JvmStatic
    fun setLicense(licensePath: String, callback: LicenseActivationCallback) {
        engineExecutor.execute {
            val result = activateLicense(licensePath)
            if (result.errorCode == 0) {
                callback.onResult(result)
            } else {
                callback.onError(result.errorCode, result.errorMessage ?: "license activation failed")
            }
        }
    }

    /**
     * 查询当前通过 [setLicense] 激活的 License 信息。
     */
    @JvmStatic
    fun getLicenseInfo(): LicenseInfo =
        licenseInfo ?: throw DingqiaoEngineException(
            DingqiaoErrorCode.LICENSE_NOT_SET,
            "license not set",
        )

    /**
     * 注册声纹：3~5 条样本，每条 3~8 秒。
     */
    @JvmStatic
    fun registerVoiceprint(params: VoiceprintRegisterParams): VoiceprintRegisterResult {
        params.audioInfo.validate()
        val count = params.samplePaths.size
        if (count !in DINGQIAO_VOICEPRINT_MIN_SAMPLES..DINGQIAO_VOICEPRINT_MAX_SAMPLES) {
            throw DingqiaoEngineException(
                DingqiaoErrorCode.VOICEPRINT_SAMPLE_COUNT,
                "sample count must be $DINGQIAO_VOICEPRINT_MIN_SAMPLES..$DINGQIAO_VOICEPRINT_MAX_SAMPLES",
            )
        }
        val store = requireStore()
        val modelPath = store.speakerModelPath()
        if (!modelPath.isFile) {
            throw DingqiaoEngineException(
                DingqiaoErrorCode.VOICEPRINT_REGISTER_FAILED,
                "speaker model not found: ${modelPath.absolutePath}",
            )
        }
        val segments = mutableListOf<FloatArray>()
        val minMs = DINGQIAO_VOICEPRINT_MIN_SEC * 1000L
        val maxMs = DINGQIAO_VOICEPRINT_MAX_SEC * 1000L
        for (path in params.samplePaths) {
            val file = File(path)
            if (!file.isFile) {
                throw DingqiaoEngineException(
                    DingqiaoErrorCode.VOICEPRINT_REGISTER_FAILED,
                    "sample not found: $path",
                )
            }
            val pcm = PcmIo.readPcm16k(file)
            val durationMs = PcmIo.durationMs(pcm.size)
            if (durationMs !in minMs..maxMs) {
                throw DingqiaoEngineException(
                    DingqiaoErrorCode.VOICEPRINT_SAMPLE_DURATION,
                    "sample duration must be ${DINGQIAO_VOICEPRINT_MIN_SEC}s..${DINGQIAO_VOICEPRINT_MAX_SEC}s: $path",
                )
            }
            segments += PcmIo.shortsToFloats(pcm)
        }
        return SpeakerEnroller(modelPath.absolutePath).use { enroller ->
            val embedding = enroller.enroll(segments)
            store.saveVoiceprint(params.samplePaths, embedding)
        }
    }

    /**
     * 删除声纹。
     */
    @JvmStatic
    fun deleteVoiceprint(voiceprintId: String) {
        val store = requireStore()
        if (!store.deleteVoiceprint(voiceprintId)) {
            throw DingqiaoEngineException(
                DingqiaoErrorCode.VOICEPRINT_NOT_FOUND,
                "voiceprint not found: $voiceprintId",
            )
        }
    }

    private fun requireContext(): Context =
        appContext ?: throw IllegalStateException("SpeechRecognizeSdk.init(context) must be called first")

    private fun ensureRuntimeInitialized(ctx: Context) {
        if (runtimeInitialized) return
        synchronized(this) {
            if (runtimeInitialized) return
            AmphionRuntime.init(ctx)
            runtimeInitialized = true
        }
    }

    private fun activateLicense(licensePath: String): LicenseActivationResult {
        val ctx = try {
            requireContext()
        } catch (t: Throwable) {
            return LicenseActivationResult(
                errorCode = DingqiaoErrorCode.ENGINE_NOT_INITIALIZED,
                errorMessage = t.message,
            )
        }
        val file = File(licensePath)
        if (!file.isFile || !file.canRead()) {
            return LicenseActivationResult(
                errorCode = DingqiaoErrorCode.LICENSE_FILE_UNREADABLE,
                errorMessage = "license file not readable: $licensePath",
            )
        }
        val text = try {
            file.readText(Charsets.UTF_8)
        } catch (t: Throwable) {
            return LicenseActivationResult(
                errorCode = DingqiaoErrorCode.LICENSE_FILE_UNREADABLE,
                errorMessage = t.message ?: "license file not readable",
            )
        }
        return try {
            synchronized(this) {
                if (runtimeInitialized) {
                    AmphionRuntime.release()
                    runtimeInitialized = false
                }
                AmphionRuntime.init(
                    ctx,
                    AmphionOptions(
                        license = text,
                        licenseAssetName = null,
                    ),
                )
                runtimeInitialized = true
                val info = AmphionRuntime.licenseStatus().toDingqiaoLicenseInfo()
                licenseInfo = info
                LicenseActivationResult(
                    errorCode = 0,
                    remainingDays = info.remainingDays,
                    authorizedFeatures = info.authorizedFeatures,
                )
            }
        } catch (t: Throwable) {
            val code = mapLicenseErrorCode(extractAsrErrorCode(t.message))
            licenseInfo = LicenseInfo(
                status = licenseStatusForError(code),
                expireTime = -1,
                remainingDays = -1,
                authorizedFeatures = emptyList(),
            )
            LicenseActivationResult(
                errorCode = code,
                errorMessage = t.message ?: "license activation failed",
            )
        }
    }

    private fun requireStore(): VoiceprintStore {
        val path = workPath ?: throw IllegalStateException("SpeechRecognizeSdk.setWorkPath() must be called first")
        return VoiceprintStore(path)
    }

    private fun AmphionLicenseStatus.toDingqiaoLicenseInfo(): LicenseInfo {
        val status = when {
            state == AmphionLicenseStatus.State.LICENSED -> 0
            errorCode == AsrErrorCode.LICENSE_EXPIRED -> 1
            state == AmphionLicenseStatus.State.NOT_INITIALIZED -> 2
            errorCode in setOf(
                AsrErrorCode.LICENSE_APP_MISMATCH,
                AsrErrorCode.LICENSE_CERT_MISMATCH,
                AsrErrorCode.LICENSE_DEVICE_MISMATCH,
            ) -> 3
            state == AmphionLicenseStatus.State.DEV_UNLICENSED -> 0
            else -> 2
        }
        return LicenseInfo(
            status = status,
            expireTime = expiresAt.toExpireTimeMillis(),
            remainingDays = expiresAt.toRemainingDays(),
            authorizedFeatures = features,
        )
    }

    private fun String.toExpireTimeMillis(): Long {
        if (isBlank()) return -1
        return try {
            LocalDate.parse(this).atStartOfDay().toInstant(ZoneOffset.UTC).toEpochMilli()
        } catch (_: Throwable) {
            -1
        }
    }

    private fun String.toRemainingDays(): Int {
        if (isBlank()) return -1
        return try {
            ChronoUnit.DAYS.between(LocalDate.now(ZoneOffset.UTC), LocalDate.parse(this)).toInt()
        } catch (_: Throwable) {
            -1
        }
    }

    private fun extractAsrErrorCode(message: String?): Int? =
        Regex("code=(\\d+)").find(message.orEmpty())?.groupValues?.getOrNull(1)?.toIntOrNull()

    private fun mapLicenseErrorCode(asrCode: Int?): Int = when (asrCode) {
        AsrErrorCode.LICENSE_MISSING -> DingqiaoErrorCode.LICENSE_FILE_UNREADABLE
        AsrErrorCode.LICENSE_MALFORMED,
        AsrErrorCode.LICENSE_SIGNATURE_INVALID,
        -> DingqiaoErrorCode.LICENSE_INVALID
        AsrErrorCode.LICENSE_EXPIRED -> DingqiaoErrorCode.LICENSE_EXPIRED
        AsrErrorCode.LICENSE_APP_MISMATCH,
        AsrErrorCode.LICENSE_CERT_MISMATCH,
        AsrErrorCode.LICENSE_DEVICE_MISMATCH,
        -> DingqiaoErrorCode.LICENSE_DEVICE_MISMATCH
        else -> DingqiaoErrorCode.LICENSE_ACTIVATION_FAILED
    }

    private fun licenseStatusForError(code: Int): Int = when (code) {
        DingqiaoErrorCode.LICENSE_EXPIRED -> 1
        DingqiaoErrorCode.LICENSE_DEVICE_MISMATCH -> 3
        else -> 2
    }
}
