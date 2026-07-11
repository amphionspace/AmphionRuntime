package com.lits.tts.sdk.internal

/**
 * On-device license feature-tier enforcement test.
 *
 * Runs the real TTS [LicenseVerifier] (armed with the built-in `BuildConfig.LICENSE_PUBLIC_KEY_B64`)
 * against three device-unbound / no-cert licenses in `androidTest/assets/lic/` — so only the
 * feature gate applies (app / cert / SN bindings are blank and skipped):
 *
 *   asr-only  -> LICENSE_FEATURE_MISSING (TTS denied)
 *   tts-only  -> OK (TTS licensed)
 *   asr+tts   -> OK (TTS licensed)
 *
 * This is the on-hardware companion to the JVM `LicenseVerifierTest`, exercising the armed
 * BuildConfig key on a real device (ART + java.security ECDSA). It requires a connected device and
 * an armed build; on an unarmed (blank-key) build the tier checks are meaningless, so the tests
 * skip via `assumeTrue`. Not run by CI (needs a device); run with `:sdk:connectedDebugAndroidTest`.
 */

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.lits.tts.sdk.BuildConfig
import com.lits.tts.sdk.TtsErrorCode
import org.junit.Assume.assumeTrue
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class LicenseTierDeviceTest {

    private val armed: Boolean = BuildConfig.LICENSE_PUBLIC_KEY_B64.isNotBlank()

    private fun readLic(name: String): String =
        InstrumentationRegistry.getInstrumentation().context.assets
            .open("lic/$name").bufferedReader(Charsets.UTF_8).use { it.readText() }

    private fun verifyTts(asset: String): LicenseVerifier.Result {
        val ctx = ApplicationProvider.getApplicationContext<Context>()
        return LicenseVerifier.verify(
            ctx = ctx,
            licenseText = readLic(asset),
            publicKeyB64 = BuildConfig.LICENSE_PUBLIC_KEY_B64,
            expiryGraceDays = 0,
            sdkMajor = BuildConfig.SDK_MAJOR,
            sdkReleaseDate = BuildConfig.SDK_RELEASE_DATE,
            requiredFeature = "TTS",
        )
    }

    @Test
    fun asrOnlyLicenseDeniesTts() {
        assumeTrue("unarmed build: tier gate is a no-op", armed)
        assertEquals(TtsErrorCode.LICENSE_FEATURE_MISSING, verifyTts("asr_only.lic").errorCode)
    }

    @Test
    fun ttsOnlyLicenseActivatesTts() {
        assumeTrue("unarmed build: tier gate is a no-op", armed)
        val r = verifyTts("tts_only.lic")
        assertEquals(TtsErrorCode.OK, r.errorCode)
        assertTrue(r.ok)
    }

    @Test
    fun asrTtsLicenseActivatesTts() {
        assumeTrue("unarmed build: tier gate is a no-op", armed)
        val r = verifyTts("asr_tts.lic")
        assertEquals(TtsErrorCode.OK, r.errorCode)
        assertTrue(r.ok)
    }
}
