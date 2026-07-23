package com.amphion.dingqiao.demo

import android.content.Context
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.CreateEngineCallback
import com.amphion.dingqiao.CreateEngineParams
import com.amphion.dingqiao.LicenseActivationCallback
import com.amphion.dingqiao.LicenseActivationResult
import com.amphion.dingqiao.PrepareRuntimeCallback
import com.amphion.dingqiao.SpeechRecognitionEngine
import com.amphion.dingqiao.SpeechRecognizeSdk
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class DqRuntimeFastLoadInstrumentedTest {
    private val targetContext: Context
        get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val testContext: Context
        get() = InstrumentationRegistry.getInstrumentation().context

    @Test
    fun coldWarmUnloadAndRuntimeReloadUsePublicLifecycle() {
        SpeechRecognizeSdk.init(targetContext)
        SpeechRecognizeSdk.setWorkPath(
            File(targetContext.getExternalFilesDir(null), "runtime_fast_load").absolutePath,
        )
        activateValidLicense()
        prepareRuntime()

        val cold = createEngine()
        cold.engine.shutdown()
        val warm = createEngine()
        warm.engine.shutdown()

        SpeechRecognizeSdk.unloadModel()
        val modelReload = createEngine()
        modelReload.engine.shutdown()

        SpeechRecognizeSdk.unloadRuntime()
        assertEquals(0, SpeechRecognizeSdk.getLicenseInfo().status)
        prepareRuntime()
        val runtimeReload = createEngine()
        runtimeReload.engine.shutdown()

        DqReport.append(
            targetContext,
            mapOf(
                "case" to "runtime-fast-load",
                "coldMs" to cold.elapsedMs,
                "warmMs" to warm.elapsedMs,
                "modelReloadMs" to modelReload.elapsedMs,
                "runtimeReloadMs" to runtimeReload.elapsedMs,
            ),
        )
        assertTrue("warm model reuse should not exceed cold load", warm.elapsedMs <= cold.elapsedMs)
    }

    private fun activateValidLicense() {
        val path = stageAsset(testContext, targetContext, "licenses/valid.lic", "lic/runtime-valid.lic")
        val done = CountDownLatch(1)
        var resultCode: Int? = null
        SpeechRecognizeSdk.setLicense(path, object : LicenseActivationCallback {
            override fun onResult(result: LicenseActivationResult) {
                resultCode = result.errorCode
                done.countDown()
            }

            override fun onError(errorCode: Int, errorMessage: String) {
                resultCode = errorCode
                done.countDown()
            }
        })
        assertTrue("setLicense callback timed out", done.await(20, TimeUnit.SECONDS))
        assertEquals("valid license must activate", 0, resultCode)
    }

    private fun prepareRuntime() {
        val done = CountDownLatch(1)
        var error: String? = null
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() {
                done.countDown()
            }

            override fun onError(errorCode: Int, errorMessage: String) {
                error = "$errorCode $errorMessage"
                done.countDown()
            }
        })
        assertTrue("prepareRuntime callback timed out", done.await(20, TimeUnit.SECONDS))
        assertEquals("prepareRuntime failed", null, error)
    }

    private fun createEngine(): TimedEngine {
        val start = SystemClock.elapsedRealtime()
        val done = CountDownLatch(1)
        var engine: SpeechRecognitionEngine? = null
        var error: String? = null
        SpeechRecognizeSdk.createEngineAsync(
            CreateEngineParams(language = "zh-CN"),
            object : CreateEngineCallback {
                override fun onSuccess(created: SpeechRecognitionEngine) {
                    engine = created
                    done.countDown()
                }

                override fun onError(errorCode: Int, errorMessage: String) {
                    error = "$errorCode $errorMessage"
                    done.countDown()
                }
            },
        )
        assertTrue("createEngineAsync callback timed out", done.await(120, TimeUnit.SECONDS))
        assertEquals("createEngineAsync failed", null, error)
        assertNotNull(engine)
        return TimedEngine(engine!!, SystemClock.elapsedRealtime() - start)
    }

    private data class TimedEngine(
        val engine: SpeechRecognitionEngine,
        val elapsedMs: Long,
    )
}
