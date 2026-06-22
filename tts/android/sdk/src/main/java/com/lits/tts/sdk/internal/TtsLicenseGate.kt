package com.lits.tts.sdk.internal

import android.content.Context
import com.lits.tts.sdk.BuildConfig
import com.lits.tts.sdk.LicenseEnforcement
import com.lits.tts.sdk.TextToSpeechException
import com.lits.tts.sdk.TtsLicenseOptions
import com.lits.tts.sdk.TtsLicenseStatus

internal object TtsLicenseGate {
    @Volatile
    private var appContext: Context? = null

    @Volatile
    private var options: TtsLicenseOptions = TtsLicenseOptions()

    @Volatile
    private var status: TtsLicenseStatus = TtsLicenseStatus.NOT_INITIALIZED

    fun init(context: Context, options: TtsLicenseOptions) {
        val ctx = context.applicationContext ?: context
        synchronized(this) {
            this.appContext = ctx
            this.options = options
            val result = verify(ctx, options)
            status = result.status
            enforceIfNeeded(result, options)
        }
    }

    fun ensureCreateAllowed() {
        val current = status
        if (current.state == TtsLicenseStatus.State.LICENSED || current.state == TtsLicenseStatus.State.DEV_UNLICENSED) {
            return
        }
        if (current.state == TtsLicenseStatus.State.INVALID && options.enforcement == LicenseEnforcement.PERMISSIVE) {
            return
        }

        val ctx = appContext ?: AndroidAppContext.tryGet()
        if (ctx == null) {
            if (BuildConfig.LICENSE_PUBLIC_KEY_B64.isBlank()) {
                status = TtsLicenseStatus(
                    state = TtsLicenseStatus.State.DEV_UNLICENSED,
                    valid = false,
                    errorCode = com.lits.tts.sdk.TtsErrorCode.OK,
                    licenseId = "",
                    customer = "",
                    applicationId = "",
                    issuedAt = "",
                    expiresAt = "",
                    installTier = "",
                    features = emptyList(),
                )
                return
            }
            throw TextToSpeechException(
                com.lits.tts.sdk.TtsErrorCode.LICENSE_MISSING,
                "TextToSpeechSdk.init(context) must be called before createEngine in licensed builds",
            )
        }

        synchronized(this) {
            appContext = ctx.applicationContext ?: ctx
            val result = verify(appContext ?: ctx, options)
            status = result.status
            enforceIfNeeded(result, options)
        }
    }

    fun licenseStatus(): TtsLicenseStatus = status

    fun deviceLicenseFingerprint(context: Context): String =
        LicenseVerifier.deviceFingerprint(context.applicationContext ?: context)

    private fun verify(context: Context, options: TtsLicenseOptions): LicenseVerifier.Result =
        LicenseVerifier.verify(
            ctx = context,
            licenseText = resolveLicenseText(context, options),
            publicKeyB64 = BuildConfig.LICENSE_PUBLIC_KEY_B64,
            expiryGraceDays = options.expiryGraceDays,
        )

    private fun resolveLicenseText(context: Context, options: TtsLicenseOptions): String? {
        options.license?.let { if (it.isNotBlank()) return it }
        val assetName = options.licenseAssetName
        if (assetName.isNullOrBlank()) return null
        return try {
            context.assets.open(assetName).bufferedReader(Charsets.UTF_8).use { it.readText() }
        } catch (_: Throwable) {
            null
        }
    }

    private fun enforceIfNeeded(result: LicenseVerifier.Result, options: TtsLicenseOptions) {
        if (!result.ok && options.enforcement == LicenseEnforcement.ENFORCE) {
            throw TextToSpeechException(
                result.errorCode,
                "TextToSpeechSdk license check failed: ${result.errorMessage ?: "unknown"}",
            )
        }
    }
}
