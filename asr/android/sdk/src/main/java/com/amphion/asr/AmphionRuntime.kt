package com.amphion.asr

import android.content.Context
import com.amphion.asr.internal.AssetInstaller
import com.amphion.asr.internal.AssetRegistry
import com.amphion.asr.internal.DeviceLicenseFingerprint
import com.amphion.asr.internal.EngineImpl
import com.amphion.asr.internal.LicenseVerifier
import com.amphion.asr.internal.Logger
import com.amphion.asr.internal.SharedPostProcessor
import com.k2fsa.sherpa.onnx.OnlineRecognizer
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * SDK 顶层入口。
 *
 * 业务方只需要这一个 object 就能完成全部接入：
 * - 单语言按需加载：[init] -> [create] -> 用 [AsrEngine] -> [release]
 * - 多语言预加载（推荐）：[init] -> [preload]([AsrLanguage.ZH_EN], [AsrLanguage.YUE_EN]) ->
 *   [create] 命中池 0 延迟 -> [AsrEngine.close] 归还池 -> [release] 全释放
 *
 * 标点 / ITN / VAD / 模型路径等内部细节都被封在 SDK 内，不暴露给调用方。
 *
 * 进程内只需 [init] 一次；之后所有 [create] 共享同一份 native 加载状态、共享后处理 pool
 * 与日志配置。
 */
public object AmphionRuntime {

    @Volatile
    private var initialized: Boolean = false

    @Volatile
    private var appContext: Context? = null

    /** 最近一次 [init] 得到的 license 状态；[licenseStatus] 对外暴露。 */
    @Volatile
    private var licenseStatusHolder: AmphionLicenseStatus? = null

    /**
     * 多语言预加载池：language → 已加载的 OnlineRecognizer。
     *
     * preload 后驻留在这里；create(language) 优先从这里拿（O(ms)）。release() 时清空。
     */
    private val asrPool: ConcurrentHashMap<AsrLanguage, OnlineRecognizer> = ConcurrentHashMap()

    /** 池里 recognizer 的"模板 config"。create 时用它判断是否能复用 */
    @Volatile
    private var poolConfig: AsrConfig? = null

    /**
     * 初始化 SDK。重复调用是幂等的（后续调用会被忽略并打 WARN 日志）。
     *
     * @param context 任意 [Context]，SDK 内部仅持有 ApplicationContext
     * @param options 全局选项，详见 [AmphionOptions]
     */
    @JvmStatic
    @JvmOverloads
    public fun init(context: Context, options: AmphionOptions = AmphionOptions()) {
        if (initialized) {
            Logger.w("AmphionRuntime.init called more than once, ignored.")
            return
        }
        synchronized(this) {
            if (initialized) return
            val ctx = context.applicationContext ?: context
            Logger.setLevel(options.logLevel)

            // 离线 license 校验。仅当构建期注入了 LICENSE_PUBLIC_KEY_B64（武装态）才真正生效；
            // 开发 / 内部构建（公钥为空）下结果为 DEV_UNLICENSED，result.ok=true，不影响使用。
            val result = LicenseVerifier.verify(
                ctx = ctx,
                licenseText = resolveLicenseText(ctx, options),
                publicKeyB64 = BuildConfig.LICENSE_PUBLIC_KEY_B64,
                expiryGraceDays = options.expiryGraceDays,
                deviceIdProvider = options.deviceIdProvider,
                sdkMajor = BuildConfig.SDK_MAJOR,
                sdkReleaseDate = BuildConfig.SDK_RELEASE_DATE,
            )
            licenseStatusHolder = result.status
            if (!result.ok) {
                Logger.e("license check failed: code=${result.errorCode} ${result.errorMessage}")
                if (options.licenseEnforcement == LicenseEnforcement.ENFORCE) {
                    throw IllegalStateException(
                        "code=${result.errorCode}: AmphionRuntime license check failed " +
                            "(${result.errorMessage}). 详见 AsrErrorCode 与 docs/INTEGRATION.md。",
                    )
                }
            }

            appContext = ctx
            initialized = true
            Logger.i(
                "AmphionRuntime initialized, version=${BuildConfig.SDK_VERSION}, " +
                    "logLevel=${options.logLevel}, license=${result.status.state}",
            )
        }
    }

    /**
     * 多语言预加载。
     *
     * 调用一次后池里就常驻全部 [languages] 的 OnlineRecognizer + 共享后处理；之后
     * [create] 命中池只需 O(ms)。建议在 splash 或 onboarding 阶段调用，放到子线程
     * （preload 内部已经使用专用线程，但本方法是同步分派的）。
     *
     * 内部三阶段：
     * 1. 解包 assets（与 [preInstall] 等价）
     * 2. 共享 punct/itn 单例加载
     * 3. 并行加载每个 language 的 OnlineRecognizer
     *
     * @param onProgress (stage, percent) 回调；stage ∈ {"install", "shared", "asr-<LANG>"}；
     *                   percent ∈ [0, 100]，每个 stage 各自走完整 0..100。运行在 SDK 后台线程
     * @return [Cancellable]：取消会跳过尚未开始的 stage；已加载的部分保留在池里
     */
    @JvmStatic
    @JvmOverloads
    public fun preload(
        context: Context,
        languages: List<AsrLanguage>,
        config: AsrConfig = AsrConfig.Builder().build(),
        onProgress: ((stage: String, percent: Int) -> Unit)? = null,
    ): Cancellable {
        checkInitialized()
        languages.forEach(::requireLanguageAvailable)
        val ctx = context.applicationContext ?: context
        val cancelFlag = AtomicBoolean(false)
        val handle = PreloadCancellable(cancelFlag)
        val thread = Thread(
            {
                try {
                    runPreload(ctx, languages, config, onProgress, cancelFlag)
                } catch (t: Throwable) {
                    Logger.e("preload failed: ${t.message}", t)
                } finally {
                    handle.markDone()
                }
            },
            "amphion-preload",
        ).apply { isDaemon = true }
        thread.start()
        return handle
    }

    /**
     * 创建一个 ASR 引擎实例。
     *
     * 当池命中时（已经 [preload] 过且 config 兼容）O(ms) 返回；否则同步走完
     * 解包 + 加载流程（5~30s 的解包 + 1~3s 的加载，建议放子线程）。
     *
     * @return 已就绪的 [AsrEngine]
     * @throws IllegalStateException 如果 [init] 未调用，或资产解包失败
     */
    @JvmStatic
    @JvmOverloads
    public fun create(
        context: Context,
        language: AsrLanguage,
        config: AsrConfig = AsrConfig.Builder().build(),
    ): AsrEngine {
        checkInitialized()
        requireLanguageAvailable(language)
        val ctx = context.applicationContext ?: context
        val createStartElapsed = android.os.SystemClock.elapsedRealtime()

        val pooled = asrPool[language]
        val poolCfg = poolConfig
        val canReusePool = pooled != null && poolCfg != null &&
            EngineImpl.isRecognizerConfigCompatible(poolCfg, config)

        val recognizer: OnlineRecognizer
        val ownsRecognizer: Boolean
        val installStats: AssetInstaller.InstallStats

        if (canReusePool) {
            recognizer = pooled!!
            ownsRecognizer = false
            installStats = AssetInstaller.InstallStats.ZERO
            Logger.i("create: pool-hit for $language, reusing pooled recognizer")
        } else {
            if (pooled != null) {
                Logger.w(
                    "create: $language pooled but config mismatch (numThreads/endpoint/hotwords), " +
                        "building dedicated recognizer",
                )
            }
            val layout = AssetInstaller.ensureInstalled(ctx, language, config)
            installStats = layout.installStats
            ensureSharedPostProcessor(layout, config, language)
            recognizer = EngineImpl.buildRecognizer(layout, config, language)
            ownsRecognizer = true
        }

        val layout = AssetInstaller.InstalledLayout.of(ctx, language, config, installStats)
        ensureSharedPostProcessor(layout, config, language)
        val impl = EngineImpl(
            language = language,
            config = config,
            recognizer = recognizer,
            ownsRecognizer = ownsRecognizer,
            layout = layout,
            createStartElapsedMs = createStartElapsed,
            assetInstallMs = installStats.installMs,
            assetTotalBytes = installStats.installBytes,
        )
        return AsrEngine.create(impl)
    }

    /**
     * 主动把 SDK 内置模型从 APK assets 解包到 internal storage（不加载 native）。
     *
     * 与 [preload] 的区别：
     * - [preInstall]：只解包到磁盘；不占 native 内存；适合"想 splash 阶段把磁盘 IO 做掉"的场景
     * - [preload]：解包 + 加载 native 模型到池里；常驻 native 内存；适合"需要语言切换 0 延迟"
     *
     * 多次调用是幂等的；SDK 升级到新版本时只会解包变化的部分。
     */
    @JvmStatic
    @JvmOverloads
    public fun preInstall(
        context: Context,
        onProgress: ((Int) -> Unit)? = null,
    ): Cancellable {
        checkInitialized()
        val ctx = context.applicationContext ?: context
        return AssetInstaller.preInstallAll(ctx, onProgress)
    }

    /** 当前 SDK 语义化版本号（与 AAR 版本一致）。 */
    @JvmStatic
    public fun version(): String = BuildConfig.SDK_VERSION

    /**
     * 查询当前 license 运行状态。
     *
     * [init] 之前返回 [AmphionLicenseStatus.State.NOT_INITIALIZED]；开发 / 内部构建（SDK 未武装
     * license）返回 [AmphionLicenseStatus.State.DEV_UNLICENSED]。典型用途：在「关于」页展示
     * 授权客户 / 到期日 / 档位，或排障时确认 SDK 是否被授权武装。
     */
    @JvmStatic
    public fun licenseStatus(): AmphionLicenseStatus =
        licenseStatusHolder ?: AmphionLicenseStatus.NOT_INITIALIZED

    /**
     * 设备 SN 授权哈希，用于申请设备白名单 `.lic`（`authorizedDeviceHashes` 字段）。
     *
     * 算法：SHA-256(normalizedSn + deviceIdSaltId)，大写 hex、无冒号。
     */
    @JvmStatic
    public fun deviceLicenseFingerprint(deviceSerial: String, deviceIdSaltId: String): String =
        DeviceLicenseFingerprint.computeFromSerial(deviceSerial, deviceIdSaltId)

    /**
     * 释放 SDK 全局资源：清空 ASR 池 + 释放共享后处理 + 重置 initialized 标记。
     *
     * 仅在能确认所有 [AsrEngine] 都已 [AsrEngine.close] 时调用。
     */
    @JvmStatic
    public fun release() {
        synchronized(this) {
            if (!initialized) return
            for ((lang, recognizer) in asrPool) {
                try {
                    recognizer.release()
                } catch (t: Throwable) {
                    Logger.w("release pooled recognizer for $lang failed: ${t.message}")
                }
            }
            asrPool.clear()
            poolConfig = null
            SharedPostProcessor.release()
            appContext = null
            licenseStatusHolder = null
            initialized = false
            Logger.i("AmphionRuntime released.")
        }
    }

    /**
     * 解析本次 init 要用的 license 文本：优先 [AmphionOptions.license] 字符串，
     * 否则尝试从 app assets 读 [AmphionOptions.licenseAssetName]；都没有则返回 null。
     */
    private fun resolveLicenseText(ctx: Context, options: AmphionOptions): String? {
        options.license?.let { if (it.isNotBlank()) return it }
        val name = options.licenseAssetName
        if (name.isNullOrBlank()) return null
        return try {
            ctx.assets.open(name).bufferedReader(Charsets.UTF_8).use { it.readText() }
        } catch (_: Throwable) {
            null
        }
    }

    internal fun checkInitialized() {
        check(initialized) {
            "AmphionRuntime.init(context) must be called before using SDK APIs " +
                "(error code=${AsrErrorCode.SDK_NOT_INITIALIZED})."
        }
    }

    /**
     * 给定 [language] 的 layout，把所需的 punct/itn 加载到共享池里。
     * 已加载过的就跳过。
     */
    private fun ensureSharedPostProcessor(
        layout: AssetInstaller.InstalledLayout,
        config: AsrConfig,
        language: AsrLanguage,
    ) {
        if (config.punctuation && layout.punctuationModel != null) {
            SharedPostProcessor.ensurePunctuation(layout.punctuationModel)
        }
        if (config.itn && layout.itnTaggerFst != null && layout.itnVerbalizerFst != null) {
            // ITN 当前只对 ZH_EN 启用；YUE_EN 不会走到这里（layout.itnTaggerFst = null）
            SharedPostProcessor.ensureItn(layout.itnTaggerFst, layout.itnVerbalizerFst)
        }
        // 注意 language 参数当前未直接使用：punct/itn 选择已经由 layout.* 字段是否非 null 表达。
        // 保留语言参数是为了未来按 language 走差异化（比如多语言 punct）。
        @Suppress("UNUSED_PARAMETER")
        language.let {}
    }

    private fun runPreload(
        ctx: Context,
        languages: List<AsrLanguage>,
        config: AsrConfig,
        onProgress: ((stage: String, percent: Int) -> Unit)?,
        cancelFlag: AtomicBoolean,
    ) {
        if (languages.isEmpty()) {
            Logger.w("preload called with empty language list")
            return
        }

        // Stage 1: 解包全部资产
        if (cancelFlag.get()) return
        onProgress?.invoke("install", 0)
        val stats = AssetInstaller.preInstallAllSync(ctx) { p ->
            onProgress?.invoke("install", p)
        }
        if (cancelFlag.get()) return

        // Stage 2: 共享 punct/itn
        onProgress?.invoke("shared", 0)
        // 任意一个 language 的 layout 都能拿到 punct/itn 路径（与 language 无关）
        val refLayout = AssetInstaller.InstalledLayout.of(ctx, languages.first(), config, stats)
        if (config.punctuation && refLayout.punctuationModel != null) {
            SharedPostProcessor.ensurePunctuation(refLayout.punctuationModel)
        }
        if (config.itn) {
            // ITN 仅 ZH_EN 启用；通过显式构造 ZH_EN layout 拿到 fst 路径
            val itnLayout = AssetInstaller.InstalledLayout.of(ctx, AsrLanguage.ZH_EN, config, stats)
            if (itnLayout.itnTaggerFst != null && itnLayout.itnVerbalizerFst != null) {
                SharedPostProcessor.ensureItn(itnLayout.itnTaggerFst, itnLayout.itnVerbalizerFst)
            }
        }
        onProgress?.invoke("shared", 100)
        if (cancelFlag.get()) return

        // Stage 3: 并行加载每个 language 的 OnlineRecognizer
        val executor = Executors.newFixedThreadPool(languages.size.coerceAtLeast(1))
        try {
            val futures = languages.map { lang ->
                executor.submit {
                    if (cancelFlag.get()) return@submit
                    onProgress?.invoke("asr-${lang.name}", 0)
                    if (asrPool[lang] != null) {
                        Logger.i("preload: $lang already in pool, skipping")
                        onProgress?.invoke("asr-${lang.name}", 100)
                        return@submit
                    }
                    val layout = AssetInstaller.InstalledLayout.of(ctx, lang, config, stats)
                    val recognizer = EngineImpl.buildRecognizer(layout, config, lang)
                    val prev = asrPool.put(lang, recognizer)
                    if (prev != null) {
                        // 极端竞争：同时两次 preload；保留先放进去那份，把刚加载的 release 掉
                        try { recognizer.release() } catch (_: Throwable) {}
                        asrPool[lang] = prev
                    }
                    onProgress?.invoke("asr-${lang.name}", 100)
                }
            }
            futures.forEach { it.get() }
        } finally {
            executor.shutdown()
            executor.awaitTermination(1, TimeUnit.SECONDS)
        }

        // 记录池模板 config，create 时按它判断是否能复用
        poolConfig = config
        Logger.i("preload done: languages=${languages.joinToString(",") { it.name }} pool=${asrPool.keys}")
    }

    private fun requireLanguageAvailable(language: AsrLanguage) {
        if (!AssetRegistry.isLanguageAvailable(language)) {
            throw IllegalStateException(
                "code=${AsrErrorCode.LANGUAGE_UNAVAILABLE}: language $language is not included " +
                    "in this zh-en-only SDK build",
            )
        }
    }

    private class PreloadCancellable(private val flag: AtomicBoolean) : Cancellable {
        @Volatile
        private var done: Boolean = false

        override fun cancel() {
            flag.set(true)
        }

        override val isDone: Boolean
            get() = done

        fun markDone() {
            done = true
        }
    }
}

/**
 * SDK 全局初始化选项。
 *
 * @property logLevel 日志最低输出级别，默认 [AmphionLogLevel.WARN]，调试期可调到 INFO/DEBUG
 * @property license 直接传入的 `.lic` 文件全文（优先于 [licenseAssetName]）；null 表示走 asset
 * @property licenseAssetName app assets 内 `.lic` 文件名，默认 `amphion-license.lic`；
 *   置 null / 空表示不从 asset 读取。仅当 SDK 被武装（构建期注入 license 公钥）时才会真正读取
 * @property expiryGraceDays 到期宽限天数（规避客户端时钟误差），默认 0；必须 >= 0
 * @property licenseEnforcement license 校验失败时的策略，默认 [LicenseEnforcement.ENFORCE]
 * @property deviceIdProvider 设备 SN 码提供方；license 包含设备白名单时必须能返回稳定 SN
 */
public data class AmphionOptions(
    public val logLevel: AmphionLogLevel = AmphionLogLevel.WARN,
    public val license: String? = null,
    public val licenseAssetName: String? = "amphion-license.lic",
    public val expiryGraceDays: Int = 0,
    public val licenseEnforcement: LicenseEnforcement = LicenseEnforcement.ENFORCE,
    public val deviceIdProvider: AmphionDeviceIdProvider? = null,
) {
    init {
        require(expiryGraceDays >= 0) { "expiryGraceDays must be >= 0, got $expiryGraceDays" }
    }
}

/** SDK 日志级别。 */
public enum class AmphionLogLevel { DEBUG, INFO, WARN, ERROR, NONE }

/**
 * 可取消句柄。
 *
 * 用于 [AmphionRuntime.preInstall] 与 [AmphionRuntime.preload] 等长任务。多次 [cancel] 是幂等的。
 */
public interface Cancellable {
    /** 取消（多次调用幂等）。 */
    public fun cancel()

    /** 已经取消或者已经结束。 */
    public val isDone: Boolean
}
