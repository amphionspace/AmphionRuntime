package com.amphion.dingqiao

import android.content.Context
import com.amphion.asr.AmphionLicenseStatus
import com.amphion.asr.AmphionOptions
import com.amphion.asr.AsrErrorCode
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.mockito.kotlin.doReturn
import org.mockito.kotlin.mock

class SpeechRecognizeSdkRuntimeApiTest {
    @Before
    fun resetBeforeTest() {
        SpeechRecognizeSdk.resetForTests()
    }

    @After
    fun resetAfterTest() {
        SpeechRecognizeSdk.resetForTests()
    }

    @Test
    fun prepareRuntimeBeforeInitReportsEngineNotInitialized() {
        var ready = false
        var errorCode: Int? = null

        SpeechRecognizeSdk.prepareRuntime(
            object : PrepareRuntimeCallback {
                override fun onReady() {
                    ready = true
                }

                override fun onError(errorCodeValue: Int, errorMessage: String) {
                    errorCode = errorCodeValue
                }
            },
        )

        assertFalse(ready)
        assertEquals(DingqiaoErrorCode.ENGINE_NOT_INITIALIZED, errorCode)
    }

    @Test
    fun setLicenseDoesNotPrepareRuntime() {
        val context = mock<Context> {
            on { applicationContext } doReturn null
            on { packageName } doReturn "com.amphion.test"
        }
        val licenseFile = kotlin.io.path.createTempFile(suffix = ".lic").toFile()
        licenseFile.writeText("development-license")
        val licenseDone = CountDownLatch(1)
        val runtimeDone = CountDownLatch(1)
        var runtimeError: Int? = null
        var licenseError: Int? = null
        var licenseErrorMessage: String? = null
        val runtime = FakeRuntimeLifecycleBridge()
        SpeechRecognizeSdk.setRuntimeBridgeForTests(runtime)

        SpeechRecognizeSdk.init(context)
        SpeechRecognizeSdk.setLicense(
            licenseFile.absolutePath,
            object : LicenseActivationCallback {
                override fun onResult(result: LicenseActivationResult) {
                    licenseDone.countDown()
                }

                override fun onError(errorCode: Int, errorMessage: String) {
                    licenseError = errorCode
                    licenseErrorMessage = errorMessage
                    licenseDone.countDown()
                }
            },
        )

        assertTrue(licenseDone.await(5, TimeUnit.SECONDS))
        assertEquals(licenseErrorMessage, null, licenseError)
        assertFalse(runtime.ready)
        assertEquals(0, SpeechRecognizeSdk.getLicenseInfo().status)

        SpeechRecognizeSdk.prepareRuntime(
            object : PrepareRuntimeCallback {
                override fun onReady() {
                    runtimeDone.countDown()
                }

                override fun onError(errorCode: Int, errorMessage: String) {
                    runtimeError = errorCode
                    runtimeDone.countDown()
                }
            },
        )

        assertTrue(runtimeDone.await(5, TimeUnit.SECONDS))
        assertEquals(null, runtimeError)
        assertTrue(runtime.ready)
        licenseFile.delete()
    }

    @Test
    fun createEngineAsyncBeforePrepareReportsEngineNotInitialized() {
        val context = mock<Context> {
            on { applicationContext } doReturn null
            on { packageName } doReturn "com.amphion.test"
        }
        val done = CountDownLatch(1)
        var errorCode: Int? = null
        SpeechRecognizeSdk.init(context)

        SpeechRecognizeSdk.createEngineAsync(
            CreateEngineParams(language = "zh"),
            object : CreateEngineCallback {
                override fun onSuccess(engine: SpeechRecognitionEngine) {
                    done.countDown()
                }

                override fun onError(errorCodeValue: Int, errorMessage: String) {
                    errorCode = errorCodeValue
                    done.countDown()
                }
            },
        )

        assertTrue(done.await(5, TimeUnit.SECONDS))
        assertEquals(DingqiaoErrorCode.ENGINE_NOT_INITIALIZED, errorCode)
    }

    @Test
    fun newSuccessCallbackBridgesToLegacyOnResultImplementation() {
        var received: SpeechRecognitionEngine? = null
        val engine = mock<SpeechRecognitionEngine>()
        val legacy = object : CreateEngineCallback {
            @Suppress("DEPRECATION")
            override fun onResult(engine: SpeechRecognitionEngine) {
                received = engine
            }
        }

        legacy.onSuccess(engine)

        assertEquals(engine, received)
    }

    @Test
    fun concurrentPrepareRuntimeIsSingleFlightAndUnloadPreservesLicense() {
        val context = mock<Context> {
            on { applicationContext } doReturn null
            on { packageName } doReturn "com.amphion.test"
        }
        val licenseFile = kotlin.io.path.createTempFile(suffix = ".lic").toFile()
        licenseFile.writeText("development-license")
        val runtime = FakeRuntimeLifecycleBridge()
        SpeechRecognizeSdk.setRuntimeBridgeForTests(runtime)
        SpeechRecognizeSdk.init(context)
        val licensed = CountDownLatch(1)
        SpeechRecognizeSdk.setLicense(
            licenseFile.absolutePath,
            object : LicenseActivationCallback {
                override fun onResult(result: LicenseActivationResult) = licensed.countDown()
                override fun onError(errorCode: Int, errorMessage: String) = licensed.countDown()
            },
        )
        assertTrue(licensed.await(5, TimeUnit.SECONDS))

        val prepared = CountDownLatch(2)
        repeat(2) {
            SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
                override fun onReady() = prepared.countDown()
                override fun onError(errorCode: Int, errorMessage: String) = prepared.countDown()
            })
        }

        assertTrue(prepared.await(5, TimeUnit.SECONDS))
        assertEquals(1, runtime.prepareCalls.get())
        SpeechRecognizeSdk.unloadRuntime()
        assertEquals(0, SpeechRecognizeSdk.getLicenseInfo().status)

        val rePrepared = CountDownLatch(1)
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() = rePrepared.countDown()
        })
        assertTrue(rePrepared.await(5, TimeUnit.SECONDS))
        assertEquals(2, runtime.prepareCalls.get())
        licenseFile.delete()
    }

    @Test
    fun latestSetLicenseWinsWhenOlderValidationFinishesLast() {
        val context = mock<Context> {
            on { applicationContext } doReturn null
            on { packageName } doReturn "com.amphion.test"
        }
        val oldLicense = kotlin.io.path.createTempFile(suffix = ".lic").toFile().apply {
            writeText("old-license")
        }
        val newLicense = kotlin.io.path.createTempFile(suffix = ".lic").toFile().apply {
            writeText("new-license")
        }
        val runtime = FakeRuntimeLifecycleBridge().apply {
            blockedLicenseText = "old-license"
        }
        SpeechRecognizeSdk.setRuntimeBridgeForTests(runtime)
        SpeechRecognizeSdk.init(context)
        val callbacks = CountDownLatch(2)

        SpeechRecognizeSdk.setLicense(oldLicense.absolutePath, countingLicenseCallback(callbacks))
        assertTrue(runtime.validationStarted.await(5, TimeUnit.SECONDS))
        SpeechRecognizeSdk.setLicense(newLicense.absolutePath, countingLicenseCallback(callbacks))
        runtime.releaseValidation.countDown()

        assertTrue(callbacks.await(5, TimeUnit.SECONDS))
        val prepared = CountDownLatch(1)
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() = prepared.countDown()
        })
        assertTrue(prepared.await(5, TimeUnit.SECONDS))
        assertEquals("new-license", runtime.lastPreparedLicense)
        oldLicense.delete()
        newLicense.delete()
    }

    private fun countingLicenseCallback(done: CountDownLatch) =
        object : LicenseActivationCallback {
            override fun onResult(result: LicenseActivationResult) = done.countDown()
            override fun onError(errorCode: Int, errorMessage: String) = done.countDown()
        }

    private class FakeRuntimeLifecycleBridge : RuntimeLifecycleBridge {
        var ready: Boolean = false
        val prepareCalls = AtomicInteger()
        var blockedLicenseText: String? = null
        val validationStarted = CountDownLatch(1)
        val releaseValidation = CountDownLatch(1)
        @Volatile var lastPreparedLicense: String? = null

        override fun validateLicense(
            context: Context,
            options: AmphionOptions,
        ): AmphionLicenseStatus {
            if (options.license == blockedLicenseText) {
                validationStarted.countDown()
                releaseValidation.await(5, TimeUnit.SECONDS)
            }
            return AmphionLicenseStatus(
                state = AmphionLicenseStatus.State.LICENSED,
                valid = true,
                errorCode = AsrErrorCode.OK,
                licenseId = "test",
                customer = "test",
                applicationId = "com.amphion.test",
                bundleName = "",
                signingCertDigest = "",
                deviceIdHashAlg = "",
                deviceIdSaltId = "",
                authorizedDeviceCount = 0,
                maintenanceUntil = "",
                issuedAt = "2026-07-23",
                expiresAt = "2026-11-23",
                installTier = "test",
                features = listOf("ASR"),
            )
        }

        override fun prepareRuntime(context: Context, options: AmphionOptions) {
            prepareCalls.incrementAndGet()
            lastPreparedLicense = options.license
            ready = true
        }

        override fun isRuntimeReady(): Boolean = ready

        override fun unloadModel() = Unit

        override fun unloadRuntime() {
            ready = false
        }
    }
}
