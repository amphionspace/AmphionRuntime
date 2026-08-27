package com.amphion.dingqiao

import android.annotation.SuppressLint
import android.content.Context
import android.os.Build
import com.amphion.asr.AmphionDeviceIdProvider
import com.amphion.asr.AmphionLogLevel
import com.amphion.asr.AmphionRuntime
import com.amphion.asr.AmphionLicenseStatus
import com.amphion.asr.AmphionOptions
import com.amphion.asr.AsrErrorCode
import com.amphion.asr.SpeakerEnroller
import java.io.File
import java.time.LocalDate
import java.time.ZoneOffset
import java.time.temporal.ChronoUnit
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executor
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicLong

/**
 * 宿主设备序列号提供器，与 HarmonyOS 鼎桥接口同名。
 *
 * 特权宿主可以在 [SpeechRecognizeSdk.init] 时注入稳定设备 SN；返回空值时授权校验按设备不匹配
 * 处理。SDK 会捕获提供器异常，避免宿主实现异常越过 License 错误边界。
 */
fun interface LicenseDeviceIdProvider {
    fun getDeviceSerial(context: Context): String?
}

/**
 * 鼎桥语音识别 SDK 入口，对齐 [语音识别SDK接口.md]。
 *
 * Android 平台须先调用 [init] 注入 [Context]，再 [setWorkPath]。
 */
object SpeechRecognizeSdk {

    @Volatile
    private var appContext: Context? = null

    @Volatile
    private var licenseDeviceIdProvider: LicenseDeviceIdProvider? = null

    @Volatile
    private var workPath: File? = null

    @Volatile
    private var licenseInfo: LicenseInfo? = null

    @Volatile
    private var activatedLicenseText: String? = null

    @Volatile
    private var runtimeInitialized: Boolean = false

    @Volatile
    private var defaultModelPrepared: Boolean = false

    @Volatile
    private var runtimeLogLevel: AmphionLogLevel = AmphionLogLevel.WARN

    @Volatile
    private var runtimeGeneration: Long = 0

    @Volatile
    private var modelGeneration: Long = 0

    private class PrepareFlight(
        val runtimeGeneration: Long,
        val modelGeneration: Long,
        val licenseText: String,
        initialCallback: PrepareRuntimeCallback,
    ) {
        val callbacks = mutableListOf(initialCallback)
    }

    private var activePrepareFlight: PrepareFlight? = null

    private val licenseRequestGeneration = AtomicLong()

    /**
     * 串行化 native runtime 的准备、发布与卸载，但不充当状态锁。
     *
     * unload 返回后不会被更早提交的 prepare 重新加载；成功回调也不会与卸载交错。
     * Java monitor 可重入，因此调用方仍可在成功回调内同步执行 unload。
     */
    private val lifecycleOperationLock = Any()

    @Volatile
    private var runtimeBridge: RuntimeLifecycleBridge = AndroidRuntimeLifecycleBridge

    private val defaultEngineExecutor: Executor = Executors.newCachedThreadPool { r ->
        Thread(r, "dingqiao-engine").apply { isDaemon = true }
    }

    @Volatile
    private var engineExecutor: Executor = defaultEngineExecutor

    /**
     * Runtime/model generations own every published engine. A lifecycle reset must close these
     * handles before releasing the pooled native recognizer; otherwise a stale engine can enter
     * OnlineRecognizer.createStream() with a freed native pointer.
     */
    private val activeEngines: MutableSet<SpeechRecognitionEngine> = ConcurrentHashMap.newKeySet()

    /**
     * Android 平台初始化（须在 [createEngine] / [registerVoiceprint] 之前调用一次）。
     */
    @JvmStatic
    fun init(context: Context) {
        init(context, null)
    }

    /**
     * Android 平台初始化，并允许特权宿主注入设备序列号提供器。
     *
     * 已初始化后更换 Context 或 provider 会使既有授权、Runtime、模型和引擎失效；调用方需重新
     * 执行 setLicense -> prepareRuntime，避免旧授权身份跨设备提供器继续生效。
     */
    @JvmStatic
    fun init(context: Context, deviceIdProvider: LicenseDeviceIdProvider?) {
        val ctx = context.applicationContext ?: context
        var shouldConfigureDiagnostics = false
        synchronized(lifecycleOperationLock) {
            val identityChanged = synchronized(this) {
                val previousContext = appContext
                previousContext != null &&
                    (previousContext !== ctx || licenseDeviceIdProvider !== deviceIdProvider)
            }
            if (identityChanged) {
                synchronized(this) {
                    licenseRequestGeneration.incrementAndGet()
                    runtimeGeneration += 1
                    modelGeneration += 1
                    runtimeInitialized = false
                    defaultModelPrepared = false
                    activatedLicenseText = null
                    licenseInfo = null
                    appContext = ctx
                    licenseDeviceIdProvider = deviceIdProvider
                    shouldConfigureDiagnostics = true
                }
                shutdownActiveEngines()
                runtimeBridge.unloadRuntime()
            } else {
                synchronized(this) {
                    if (appContext == null) shouldConfigureDiagnostics = true
                    appContext = ctx
                    licenseDeviceIdProvider = deviceIdProvider
                }
            }
        }
        if (shouldConfigureDiagnostics && DiagnosticsModule.isBuildEnabled()) {
            runCatching { ctx.filesDir }.getOrNull()?.let(DiagnosticsModule::setRootPath)
            runCatching {
                ctx.assets.open("amphion-models/manifest.json").bufferedReader()
                    .use { DiagnosticsModule.setDeliveredModelManifest(it.readText()) }
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

    /** 查询当前 SDK 工作目录；尚未调用 [setWorkPath] 时返回空字符串。 */
    @JvmStatic
    fun getWorkPath(): String = workPath?.path.orEmpty()

    /**
     * 设置 Core Runtime 日志阈值。应在 [prepareRuntime] 前调用，确保初始化和模型加载日志使用该等级。
     *
     * 该配置只影响日志输出，不改变识别、声纹、Speaker VAD 或生命周期行为。
     */
    @JvmStatic
    fun setLogLevel(logLevel: AmphionLogLevel) {
        runtimeLogLevel = logLevel
    }

    /**
     * @deprecated Diagnostics capture is selected by the AAR build variant. This method is kept
     * only for source compatibility and intentionally cannot enable capture at runtime.
     */
    @JvmStatic
    @Deprecated("Use the dedicated diagnostics artifact")
    fun configureDiagnostics(@Suppress("UNUSED_PARAMETER") options: DiagnosticOptions) = Unit

    /** Asynchronously exports diagnostics collected by a dedicated diagnostics AAR. */
    @JvmStatic
    fun exportDiagnostics(callback: DiagnosticExportCallback) {
        engineExecutor.execute {
            try {
                callback.onSuccess(DiagnosticsModule.export())
            } catch (t: Throwable) {
                callback.onError(
                    DingqiaoErrorCode.INTERNAL_ERROR,
                    "exportDiagnostics failed: ${t.message ?: t.javaClass.simpleName}",
                )
            }
        }
    }

    /**
     * 设备 SN 授权哈希，用于申请设备白名单 license（无需先 [init]）。
     */
    @JvmStatic
    fun deviceLicenseFingerprint(deviceSerial: String, deviceIdSaltId: String): String =
        AmphionRuntime.deviceLicenseFingerprint(deviceSerial, deviceIdSaltId)

    /**
     * 创建识别引擎（同步）。
     */
    @JvmStatic
    fun createEngine(params: CreateEngineParams): SpeechRecognitionEngine {
        return synchronized(lifecycleOperationLock) {
            val ctx = requireContext()
            requireRuntimeReady()
            val store = requireStore()
            val speakerModel = store.speakerModelPath().takeIf { it.isFile }?.absolutePath
            lateinit var created: DingqiaoRecognitionEngine
            created = DingqiaoRecognitionEngine.create(
                appContext = ctx,
                params = params,
                voiceprintStore = store,
                speakerModelPath = speakerModel,
                onShutdown = { activeEngines.remove(it) },
            )
            activeEngines.add(created)
            created
        }
    }

    /**
     * 创建识别引擎（异步回调）。
     */
    @JvmStatic
    fun createEngineAsync(params: CreateEngineParams, callback: CreateEngineCallback) {
        val generation = runtimeGeneration
        val createModelGeneration = modelGeneration
        engineExecutor.execute {
            var delivered = false
            try {
                val engine = createEngine(params)
                synchronized(lifecycleOperationLock) {
                    val accepted = synchronized(this) {
                        !(
                            generation != runtimeGeneration ||
                            createModelGeneration != modelGeneration ||
                            !runtimeInitialized ||
                            !runtimeBridge.isRuntimeReady()
                        )
                    }
                    if (!accepted) {
                        engine.shutdown()
                        throw DingqiaoEngineException(
                            DingqiaoErrorCode.ENGINE_NOT_INITIALIZED,
                            "createEngineAsync cancelled by unloadRuntime",
                        )
                    }
                    delivered = true
                    callback.onSuccess(engine)
                }
            } catch (t: Throwable) {
                if (delivered) return@execute
                val code = (t as? DingqiaoEngineException)?.errorCode
                    ?: DingqiaoErrorCode.CREATE_ENGINE_FAILED
                callback.onError(code, t.message ?: "createEngine failed")
            }
        }
    }

    /**
     * 旧版 Android 异步重载，保留给已有调用方。
     */
    @JvmStatic
    @Deprecated("Use createEngineAsync(params, callback)")
    fun createEngine(params: CreateEngineParams, callback: CreateEngineCallback) {
        createEngineAsync(params, callback)
    }

    /**
     * 设置 License 文件路径并异步激活。须在 [createEngine] 前调用；再次调用会覆盖当前进程内状态。
     */
    @JvmStatic
    fun setLicense(licensePath: String, callback: LicenseActivationCallback) {
        val requestGeneration = licenseRequestGeneration.incrementAndGet()
        engineExecutor.execute {
            val result = activateLicense(licensePath, requestGeneration)
            if (result.errorCode == 0) {
                callback.onResult(result)
            } else {
                callback.onError(result.errorCode, result.errorMessage)
            }
        }
    }

    /**
     * 准备 SDK Runtime，并在 SDK 内部预加载默认中英识别模型。调用前必须完成 [init] 和
     * 成功的 [setLicense]；[PrepareRuntimeCallback.onReady] 返回后，默认
     * `createEngineAsync(language="zh-CN")` 走模型池快路径。
     */
    @JvmStatic
    fun prepareRuntime(callback: PrepareRuntimeCallback) {
        val ctx = appContext
        if (ctx == null) {
            callback.onError(
                DingqiaoErrorCode.ENGINE_NOT_INITIALIZED,
                "SpeechRecognizeSdk.init must be called first",
            )
            return
        }
        synchronized(this) {
            val flight = activePrepareFlight
            if (
                flight != null &&
                flight.runtimeGeneration == runtimeGeneration &&
                flight.modelGeneration == modelGeneration &&
                flight.licenseText == activatedLicenseText
            ) {
                flight.callbacks += callback
                return
            }
        }
        var flightToStart: PrepareFlight? = null
        var immediateError: Pair<Int, String>? = null
        var alreadyReady = false
        synchronized(lifecycleOperationLock) {
            synchronized(this) {
                val activeLicense = activatedLicenseText
                if (activeLicense == null || licenseInfo == null) {
                    immediateError = DingqiaoErrorCode.LICENSE_NOT_SET to
                        "setLicense must succeed before prepareRuntime"
                } else {
                    val flight = activePrepareFlight
                    if (
                        flight != null &&
                        flight.runtimeGeneration == runtimeGeneration &&
                        flight.modelGeneration == modelGeneration &&
                        flight.licenseText == activeLicense
                    ) {
                        flight.callbacks += callback
                    } else if (runtimeBridge.isRuntimeReady() && defaultModelPrepared) {
                        runtimeInitialized = true
                        alreadyReady = true
                    } else {
                        PrepareFlight(
                            runtimeGeneration = runtimeGeneration,
                            modelGeneration = modelGeneration,
                            licenseText = activeLicense,
                            initialCallback = callback,
                        ).also {
                            activePrepareFlight = it
                            flightToStart = it
                        }
                    }
                }
            }
            if (immediateError != null) {
                callback.onError(immediateError!!.first, immediateError!!.second)
                return
            }
            if (alreadyReady) {
                callback.onReady()
                return
            }
        }
        val flight = flightToStart ?: return

        engineExecutor.execute {
            synchronized(lifecycleOperationLock) {
                var errorCode: Int? = null
                var errorMessage = ""
                var preparedModelGeneration: Long? = null
                try {
                    val needsPrepare = synchronized(this) {
                        if (flight.runtimeGeneration != runtimeGeneration) {
                            throw IllegalStateException("prepareRuntime cancelled by unloadRuntime")
                        }
                        if (flight.modelGeneration != modelGeneration) {
                            throw IllegalStateException("prepareRuntime cancelled by unloadModel")
                        }
                        !runtimeBridge.isRuntimeReady() || !defaultModelPrepared
                    }
                    if (needsPrepare) {
                        try {
                            runtimeBridge.prepareRuntime(
                                ctx,
                                AmphionOptions(
                                    logLevel = runtimeLogLevel,
                                    license = flight.licenseText,
                                    licenseAssetName = null,
                                    deviceIdProvider = effectiveDeviceIdProvider(),
                                ),
                            )
                        } catch (prepareFailure: Throwable) {
                            try {
                                runtimeBridge.unloadRuntime()
                            } catch (cleanupFailure: Throwable) {
                                prepareFailure.addSuppressed(cleanupFailure)
                            }
                            throw prepareFailure
                        }
                    }
                    synchronized(this) {
                        if (
                            flight.runtimeGeneration != runtimeGeneration ||
                            flight.modelGeneration != modelGeneration ||
                            !runtimeBridge.isRuntimeReady()
                        ) {
                            throw IllegalStateException("prepareRuntime cancelled by unloadRuntime")
                        }
                        runtimeInitialized = true
                        defaultModelPrepared = true
                        preparedModelGeneration = modelGeneration
                    }
                } catch (t: Throwable) {
                    synchronized(this) {
                        if (
                            flight.runtimeGeneration == runtimeGeneration &&
                            flight.modelGeneration == modelGeneration
                        ) {
                            runtimeInitialized = false
                            defaultModelPrepared = false
                        }
                    }
                    errorCode = mapLicenseErrorCode(extractAsrErrorCode(t.message))
                        .takeUnless { it == DingqiaoErrorCode.LICENSE_ACTIVATION_FAILED }
                        ?: DingqiaoErrorCode.ENGINE_NOT_INITIALIZED
                    errorMessage = t.message ?: "prepareRuntime failed"
                }

                val callbacks = synchronized(this) {
                    if (activePrepareFlight === flight) {
                        activePrepareFlight = null
                    }
                    flight.callbacks.toList().also {
                        flight.callbacks.clear()
                    }
                }
                callbacks.forEach { pendingCallback ->
                    try {
                        val callbackError = if (errorCode != null) {
                            errorCode to errorMessage
                        } else {
                            val stillReady = synchronized(this) {
                                flight.runtimeGeneration == runtimeGeneration &&
                                    flight.modelGeneration == modelGeneration &&
                                    preparedModelGeneration == flight.modelGeneration &&
                                    runtimeInitialized &&
                                    defaultModelPrepared &&
                                    runtimeBridge.isRuntimeReady()
                            }
                            if (stillReady) {
                                null
                            } else {
                                DingqiaoErrorCode.ENGINE_NOT_INITIALIZED to
                                    "prepareRuntime result invalidated by lifecycle change"
                            }
                        }
                        if (callbackError == null) {
                            pendingCallback.onReady()
                        } else {
                            pendingCallback.onError(callbackError.first, callbackError.second)
                        }
                    } catch (_: Throwable) {
                        // One caller callback must not prevent the remaining single-flight waiters.
                    }
                }
            }
        }
    }

    /**
     * 查询当前生效的 License 信息。
     *
     * 优先返回 [setLicense] 显式激活的状态；若宿主通过默认 asset
     * `amphion-license.lic` 授权，则回落到 AmphionRuntime 当前生效状态。
     */
    @JvmStatic
    fun getLicenseInfo(): LicenseInfo {
        licenseInfo?.let { return it }
        if (runtimeInitialized) {
            val info = AmphionRuntime.licenseStatus().toDingqiaoLicenseInfo()
            if (info.status != 2) return info
        }
        throw DingqiaoEngineException(
            DingqiaoErrorCode.LICENSE_NOT_SET,
            "license not set",
        )
    }

    /**
     * 注册声纹：至少 1 条样本，每条 3~8 秒；多段样本可提升稳定性但不是硬限制。
     */
    @JvmStatic
    fun registerVoiceprint(params: VoiceprintRegisterParams): VoiceprintRegisterResult {
        params.audioInfo.validate()
        val count = params.samplePaths.size
        if (count < DINGQIAO_VOICEPRINT_MIN_SAMPLES) {
            throw DingqiaoEngineException(
                DingqiaoErrorCode.VOICEPRINT_SAMPLE_COUNT,
                "sample count must be >= $DINGQIAO_VOICEPRINT_MIN_SAMPLES",
            )
        }
        val store = requireStore()
        val modelPath = store.speakerModelPath()
        DingqiaoSpeakerModelAssets.ensureInstalled(requireContext(), modelPath)
        if (!DingqiaoSpeakerModelAssets.isReady(modelPath)) {
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
     * 注册声纹（异步回调）。注册需加载 ~38MB 声纹模型并计算 embedding，属重操作；
     * 若从 UI 线程触发（如"注册"按钮），务必使用本重载，避免主线程卡顿 / ANR。
     */
    @JvmStatic
    fun registerVoiceprint(params: VoiceprintRegisterParams, callback: VoiceprintRegisterCallback) {
        engineExecutor.execute {
            try {
                callback.onResult(registerVoiceprint(params))
            } catch (t: Throwable) {
                val code = (t as? DingqiaoEngineException)?.errorCode
                    ?: DingqiaoErrorCode.VOICEPRINT_REGISTER_FAILED
                callback.onError(code, t.message ?: "registerVoiceprint failed")
            }
        }
    }

    /**
     * 删除声纹。
     */
    @JvmStatic
    fun deleteVoiceprint(voiceprintId: String): Boolean {
        val store = requireStore()
        if (!store.deleteVoiceprint(voiceprintId)) {
            throw DingqiaoEngineException(
                DingqiaoErrorCode.VOICEPRINT_NOT_FOUND,
                "voiceprint not found: $voiceprintId",
            )
        }
        return true
    }

    /**
     * 显式安装声纹模型，避免把 38MB 声纹资产复制计入普通 ASR createEngine 冷启动。
     */
    @JvmStatic
    fun preloadVoiceprintModel(): Boolean {
        return try {
            val store = requireStore()
            val modelPath = store.speakerModelPath()
            DingqiaoSpeakerModelAssets.ensureInstalled(requireContext(), modelPath)
            DingqiaoSpeakerModelAssets.isReady(modelPath)
        } catch (_: Throwable) {
            false
        }
    }

    private fun requireContext(): Context =
        appContext ?: throw IllegalStateException("SpeechRecognizeSdk.init(context) must be called first")

    private fun requireRuntimeReady() {
        if (!runtimeInitialized || !runtimeBridge.isRuntimeReady()) {
            throw DingqiaoEngineException(
                DingqiaoErrorCode.ENGINE_NOT_INITIALIZED,
                "prepareRuntime.onReady must complete before createEngine",
            )
        }
    }

    private fun activateLicense(
        licensePath: String,
        requestGeneration: Long,
    ): LicenseActivationResult {
        val ctx = try {
            requireContext()
        } catch (t: Throwable) {
            return LicenseActivationResult(
                errorCode = DingqiaoErrorCode.ENGINE_NOT_INITIALIZED,
                errorMessage = t.message ?: "SDK is not initialized",
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
            val status = runtimeBridge.validateLicense(
                ctx,
                AmphionOptions(
                    logLevel = runtimeLogLevel,
                    license = text,
                    licenseAssetName = null,
                    deviceIdProvider = effectiveDeviceIdProvider(),
                ),
            )
            if (status.errorCode != AsrErrorCode.OK) {
                throw IllegalStateException("code=${status.errorCode}: ${status.state}")
            }
            val result: LicenseActivationResult
            synchronized(lifecycleOperationLock) {
                val shouldUnloadRuntime: Boolean
                synchronized(this) {
                    if (requestGeneration != licenseRequestGeneration.get()) {
                        return LicenseActivationResult(
                            errorCode = DingqiaoErrorCode.LICENSE_ACTIVATION_FAILED,
                            errorMessage = "superseded by a newer setLicense request",
                        )
                    }
                    runtimeGeneration += 1
                    modelGeneration += 1
                    shouldUnloadRuntime = runtimeBridge.isRuntimeReady()
                    runtimeInitialized = false
                    defaultModelPrepared = false
                    activatedLicenseText = text
                    val info = status.toDingqiaoLicenseInfo()
                    licenseInfo = info
                    result = LicenseActivationResult(
                        errorCode = 0,
                        remainingDays = info.remainingDays,
                        authorizedFeatures = info.authorizedFeatures,
                    )
                }
                if (shouldUnloadRuntime) {
                    shutdownActiveEngines()
                    runtimeBridge.unloadRuntime()
                }
            }
            result
        } catch (t: Throwable) {
            val code = mapLicenseErrorCode(extractAsrErrorCode(t.message))
            if (activatedLicenseText == null) {
                licenseInfo = LicenseInfo(
                    status = licenseStatusForError(code),
                    expireTime = -1,
                    remainingDays = -1,
                    authorizedFeatures = emptyList(),
                )
            }
            LicenseActivationResult(
                errorCode = code,
                errorMessage = t.message ?: "license activation failed",
            )
        }
    }

    @JvmStatic
    fun unloadModel() {
        synchronized(lifecycleOperationLock) {
            synchronized(this) {
                modelGeneration += 1
                defaultModelPrepared = false
            }
            shutdownActiveEngines()
            runtimeBridge.unloadModel()
        }
    }

    @JvmStatic
    fun unloadRuntime() {
        synchronized(lifecycleOperationLock) {
            synchronized(this) {
                runtimeGeneration += 1
                modelGeneration += 1
                runtimeInitialized = false
                defaultModelPrepared = false
            }
            shutdownActiveEngines()
            runtimeBridge.unloadRuntime()
        }
    }

    internal fun resetForTests() {
        synchronized(lifecycleOperationLock) {
            synchronized(this) {
                licenseRequestGeneration.incrementAndGet()
                runtimeGeneration += 1
                modelGeneration += 1
                runtimeInitialized = false
                defaultModelPrepared = false
                runtimeLogLevel = AmphionLogLevel.WARN
                activatedLicenseText = null
                licenseInfo = null
                workPath = null
                appContext = null
                licenseDeviceIdProvider = null
                engineExecutor = defaultEngineExecutor
                DiagnosticsModule.resetForTests()
            }
            shutdownActiveEngines()
            runtimeBridge.unloadRuntime()
            runtimeBridge = AndroidRuntimeLifecycleBridge
        }
    }

    internal fun trackEngine(engine: SpeechRecognitionEngine) {
        activeEngines.add(engine)
    }

    private fun shutdownActiveEngines() {
        activeEngines.toList().forEach { engine ->
            try {
                if (engine is DingqiaoRecognitionEngine) {
                    engine.invalidateFromRuntime()
                } else {
                    engine.shutdown()
                }
            } catch (_: Throwable) {
                // Runtime invalidation still has to release the native pool. The handle is removed
                // even if a customer implementation throws from its idempotent shutdown method.
            } finally {
                activeEngines.remove(engine)
            }
        }
    }

    internal fun setRuntimeBridgeForTests(bridge: RuntimeLifecycleBridge) {
        runtimeBridge = bridge
    }

    internal fun setEngineExecutorForTests(executor: Executor) {
        engineExecutor = executor
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
        AsrErrorCode.LICENSE_APP_MISMATCH -> DingqiaoErrorCode.LICENSE_APP_MISMATCH
        AsrErrorCode.LICENSE_CERT_MISMATCH -> DingqiaoErrorCode.LICENSE_CERT_MISMATCH
        AsrErrorCode.LICENSE_DEVICE_MISMATCH -> DingqiaoErrorCode.LICENSE_DEVICE_MISMATCH
        else -> DingqiaoErrorCode.LICENSE_ACTIVATION_FAILED
    }

    private fun licenseStatusForError(code: Int): Int = when (code) {
        DingqiaoErrorCode.LICENSE_EXPIRED -> 1
        DingqiaoErrorCode.LICENSE_APP_MISMATCH,
        DingqiaoErrorCode.LICENSE_CERT_MISMATCH,
        DingqiaoErrorCode.LICENSE_DEVICE_MISMATCH,
        -> 3
        else -> 2
    }

    private fun effectiveDeviceIdProvider(): AmphionDeviceIdProvider =
        licenseDeviceIdProvider?.let(::DingqiaoDeviceIdProviderAdapter)
            ?: DingqiaoDeviceIdProvider

    private class DingqiaoDeviceIdProviderAdapter(
        private val delegate: LicenseDeviceIdProvider,
    ) : AmphionDeviceIdProvider {
        override fun getDeviceSerial(context: Context): String? =
            runCatching { delegate.getDeviceSerial(context) }.getOrNull()
    }

    private object DingqiaoDeviceIdProvider : AmphionDeviceIdProvider {
        override fun getDeviceSerial(context: Context): String? = readDeviceSerial()

        @SuppressLint("HardwareIds", "MissingPermission")
        private fun readDeviceSerial(): String? =
            firstUsableSerial(
                runCatching {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                        Build.getSerial()
                    } else {
                        @Suppress("DEPRECATION")
                        Build.SERIAL
                    }
                }.getOrNull(),
                readSystemProperty("ro.serialno"),
                readSystemProperty("ro.boot.serialno"),
                readSystemProperty("ril.serialnumber"),
                readGetprop("ro.serialno"),
                readGetprop("ro.boot.serialno"),
            )

        private fun firstUsableSerial(vararg candidates: String?): String? =
            candidates
                .asSequence()
                .mapNotNull { it?.trim() }
                .firstOrNull { it.isNotBlank() && !it.equals(Build.UNKNOWN, ignoreCase = true) }

        private fun readSystemProperty(key: String): String? =
            runCatching {
                val clazz = Class.forName("android.os.SystemProperties")
                val get = clazz.getMethod("get", String::class.java)
                get.invoke(null, key) as? String
            }.getOrNull()

        private fun readGetprop(key: String): String? =
            runCatching {
                val process = ProcessBuilder("getprop", key).redirectErrorStream(true).start()
                process.inputStream.bufferedReader().use { it.readText() }.trim()
            }.getOrNull()
    }
}
