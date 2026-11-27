package com.lits.tts.sdk.internal

import androidx.test.platform.app.InstrumentationRegistry
import com.lits.tts.sdk.Callback
import com.lits.tts.sdk.LicenseActivationResult
import com.lits.tts.sdk.TextToSpeechSdk
import com.lits.tts.sdk.TtsDeviceIdProvider
import com.lits.tts.sdk.TtsErrorCode
import com.lits.tts.sdk.TtsLicenseOptions
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test

/** 由验收脚本提供设备绑定的真实授权；授权正文和设备标识不进入测试源码。 */
class LicenseReactivationDeviceTest {
    @Test fun fileActivationPreservesHostIdentityAndRejectsWrongFeature() {
        val args = InstrumentationRegistry.getArguments()
        val validPath = args.getString("ttsLicenseFile")
        val asrPath = args.getString("asrLicenseFile")
        val serialPath = args.getString("deviceSerialFile")
        assumeTrue("需要预置设备绑定的 TTS、ASR 授权和设备标识文件",
            validPath != null && asrPath != null && serialPath != null)
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val serial = File(serialPath!!).readText().trim()
        assertTrue(serial.isNotEmpty())
        val options = TtsLicenseOptions(
            license = File(validPath!!).readText(), licenseAssetName = null,
            deviceIdProvider = TtsDeviceIdProvider { serial },
        )
        try {
            TextToSpeechSdk.init(context, options)
            assertTrue(TextToSpeechSdk.licenseStatus().valid)
            assertEquals(TtsErrorCode.OK, activate(validPath))
            assertTrue(TextToSpeechSdk.licenseStatus().valid)
            assertEquals(TtsErrorCode.LICENSE_FEATURE_MISSING, activate(asrPath!!))
            assertFalse(TextToSpeechSdk.licenseStatus().valid)
            assertEquals(TtsErrorCode.OK, activate(validPath))
            assertTrue(TextToSpeechSdk.licenseStatus().valid)
        } finally {
            LicenseGuard.resetForTest()
        }
    }

    private fun activate(path: String): Int {
        val done = CountDownLatch(1)
        var code = -1
        TextToSpeechSdk.setLicense(path, object : Callback<LicenseActivationResult> {
            override fun onSuccess(result: LicenseActivationResult) {
                code = result.errorCode
                done.countDown()
            }
            override fun onError(errorCode: Int, errorMessage: String) {
                code = errorCode
                done.countDown()
            }
        })
        assertTrue("授权回调超时", done.await(30, TimeUnit.SECONDS))
        return code
    }
}
