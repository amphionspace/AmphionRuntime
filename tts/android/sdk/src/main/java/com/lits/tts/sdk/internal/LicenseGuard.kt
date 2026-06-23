package com.lits.tts.sdk.internal

import android.content.Context
import com.lits.tts.sdk.BuildConfig
import com.lits.tts.sdk.LicenseEnforcement
import com.lits.tts.sdk.TextToSpeechException
import com.lits.tts.sdk.TtsLicenseOptions
import com.lits.tts.sdk.TtsLicenseStatus

/**
 * License 运行时门禁。集中持有一次性校验结果与强制策略。
 *
 * 接入点设计（第一性原理）：
 * - police 用强制的 `AmphionRuntime.init(context)` 拿 Context 并验签；TTS SDK 通过
 *   [AndroidAppContext] 反射自动发现 ApplicationContext，故不强制业务方先 init——
 *   既兼容现有「直接 createEngine」的调用方与纯 JVM 单测，又在真机上仍能强制校验。
 * - [configureAndVerify] 是 police 风格的显式入口（[com.lits.tts.sdk.TextToSpeechSdk.init]），
 *   业务方可在启动时主动调用以传入 license 文本 / 策略并尽早暴露授权问题。
 * - [gate] 在 createEngine（模型加载、价值所在）入口调用：若未显式 init，则用自动发现的
 *   Context 懒校验一次并缓存。无 Context（纯 JVM 单测）或未武装（公钥为空）一律放行。
 */
internal object LicenseGuard {

    @Volatile
    private var cached: LicenseVerifier.Result? = null

    @Volatile
    private var enforcement: LicenseEnforcement = LicenseEnforcement.ENFORCE

    /** police 风格显式入口：用业务方给定的 [context] / [options] 验签并缓存。ENFORCE 下失败抛异常。 */
    @Synchronized
    fun configureAndVerify(context: Context, options: TtsLicenseOptions) {
        enforcement = options.licenseEnforcement
        val ctx = context.applicationContext ?: context
        val result = LicenseVerifier.verify(
            ctx = ctx,
            licenseText = resolveLicenseText(ctx, options),
            publicKeyB64 = BuildConfig.LICENSE_PUBLIC_KEY_B64,
            expiryGraceDays = options.expiryGraceDays,
            deviceIdProvider = options.deviceIdProvider,
            sdkMajor = BuildConfig.SDK_MAJOR,
            sdkReleaseDate = BuildConfig.SDK_RELEASE_DATE,
        )
        cached = result
        if (!result.ok && enforcement == LicenseEnforcement.ENFORCE) {
            throw licenseException(result)
        }
    }

    /** createEngine 门禁：复用缓存结果，未 init 时懒校验。ENFORCE 下失败抛异常。 */
    fun gate() {
        val result = cached ?: lazyVerify()
        if (!result.ok && enforcement == LicenseEnforcement.ENFORCE) {
            throw licenseException(result)
        }
    }

    /** 查询当前 license 状态：尚未触发任何校验时返回 NOT_INITIALIZED。 */
    fun status(): TtsLicenseStatus = cached?.status ?: TtsLicenseStatus.NOT_INITIALIZED

    @Synchronized
    private fun lazyVerify(): LicenseVerifier.Result {
        cached?.let { return it }
        val ctx = AndroidAppContext.tryGet()
        val result = if (ctx == null) {
            // 无 Context（纯 JVM 单测 / 不在 Android 进程内）：无法校验，按未武装的开发态放行。
            // 真机 release 下 AndroidAppContext 必能拿到 ApplicationContext，不会走到这里。
            LicenseVerifier.devResult("")
        } else {
            LicenseVerifier.verify(
                ctx = ctx,
                licenseText = resolveLicenseText(ctx, TtsLicenseOptions()),
                publicKeyB64 = BuildConfig.LICENSE_PUBLIC_KEY_B64,
                expiryGraceDays = 0,
                deviceIdProvider = null,
                sdkMajor = BuildConfig.SDK_MAJOR,
                sdkReleaseDate = BuildConfig.SDK_RELEASE_DATE,
            )
        }
        cached = result
        return result
    }

    /**
     * 解析本次校验要用的 license 文本：优先 [TtsLicenseOptions.license] 字符串，
     * 否则尝试从 app assets 读 [TtsLicenseOptions.licenseAssetName]；都没有则返回 null。
     */
    private fun resolveLicenseText(ctx: Context, options: TtsLicenseOptions): String? {
        options.license?.let { if (it.isNotBlank()) return it }
        val name = options.licenseAssetName
        if (name.isNullOrBlank()) return null
        return try {
            ctx.assets.open(name).bufferedReader(Charsets.UTF_8).use { it.readText() }
        } catch (_: Throwable) {
            null
        }
    }

    private fun licenseException(result: LicenseVerifier.Result): TextToSpeechException =
        TextToSpeechException(
            result.errorCode,
            "license check failed (code=${result.errorCode}): ${result.errorMessage ?: "unauthorized"}",
        )

    /** 仅供单元测试复位静态状态。 */
    internal fun resetForTest() {
        cached = null
        enforcement = LicenseEnforcement.ENFORCE
    }
}
