package com.amphion.asr

import android.content.Context
import com.amphion.asr.internal.Logger

/**
 * SDK 全局入口。
 *
 * 集成方在进程内仅调用一次 [init]，之后所有 [AsrEngine] 实例都共享同一个 native 加载状态与日志配置。
 * 调用 [release] 之后再次使用任何 SDK API 都会得到 [AsrErrorCode.NATIVE_CRASH] 错误（不会崩溃进程）。
 *
 * 线程安全性：[init] / [release] 必须在主线程调用一次，其他方法可以在任意线程调用。
 *
 * 典型用法：
 * ```
 * class App : Application() {
 *     override fun onCreate() {
 *         super.onCreate()
 *         AsrSdk.init(this, AsrSdkOptions(logLevel = AsrLogLevel.WARN))
 *     }
 * }
 * ```
 */
public object AsrSdk {

    @Volatile
    private var initialized: Boolean = false

    @Volatile
    private var appContext: Context? = null

    /**
     * 初始化 SDK。重复调用是幂等的（后续调用会被忽略）。
     *
     * @param context 任意 [Context]，SDK 会持有其 ApplicationContext（不会泄漏 Activity）
     * @param options 全局选项；不传使用默认值
     * @throws IllegalStateException 如果 [release] 之后再次调用 [init]，需要重启进程
     */
    @JvmStatic
    @JvmOverloads
    public fun init(context: Context, options: AsrSdkOptions = AsrSdkOptions()) {
        if (initialized) {
            Logger.w("AsrSdk.init called more than once, ignored.")
            return
        }
        synchronized(this) {
            if (initialized) return
            appContext = context.applicationContext ?: context
            Logger.setLevel(options.logLevel)
            Logger.setHttpTimeoutMs(options.httpTimeoutMs)
            initialized = true
            Logger.i("AsrSdk initialized, version=${BuildConfig.SDK_VERSION}, logLevel=${options.logLevel}")
        }
    }

    /**
     * 释放 SDK 全局资源。仅在你能确认所有 [AsrEngine] 都已 [AsrEngine.close] 时调用。
     */
    @JvmStatic
    public fun release() {
        synchronized(this) {
            if (!initialized) return
            appContext = null
            initialized = false
            Logger.i("AsrSdk released.")
        }
    }

    /** 当前 SDK 语义化版本号，例如 "0.1.0"。 */
    @JvmStatic
    public fun version(): String = BuildConfig.SDK_VERSION

    /** 内部使用：是否已经 init。 */
    internal fun checkInitialized() {
        check(initialized) { "AsrSdk.init(context) must be called before using SDK APIs." }
    }

    /** 内部使用：拿 ApplicationContext。 */
    internal fun requireContext(): Context =
        appContext ?: error("AsrSdk not initialized")
}

/**
 * SDK 全局初始化选项。
 *
 * @property logLevel 日志最低输出级别，默认 [AsrLogLevel.WARN]
 * @property httpTimeoutMs 模型下载的连接 + 读取超时，单位毫秒，默认 30000
 */
public data class AsrSdkOptions(
    public val logLevel: AsrLogLevel = AsrLogLevel.WARN,
    public val httpTimeoutMs: Int = 30_000,
)

/** SDK 日志级别。 */
public enum class AsrLogLevel { DEBUG, INFO, WARN, ERROR, NONE }
