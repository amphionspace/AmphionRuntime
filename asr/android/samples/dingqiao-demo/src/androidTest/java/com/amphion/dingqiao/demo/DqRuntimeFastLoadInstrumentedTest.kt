package com.amphion.dingqiao.demo

import android.content.Context
import android.os.Debug
import android.os.SystemClock
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.AudioInfo
import com.amphion.dingqiao.CreateEngineCallback
import com.amphion.dingqiao.CreateEngineParams
import com.amphion.dingqiao.LicenseActivationCallback
import com.amphion.dingqiao.LicenseActivationResult
import com.amphion.dingqiao.PrepareRuntimeCallback
import com.amphion.dingqiao.SpeechRecognitionEngine
import com.amphion.dingqiao.SpeechRecognizeSdk
import com.amphion.dingqiao.StartParams
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
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
        val audioNames = mainWavs(testContext)
        assertTrue("runtime fast-load gate requires injected real PCM", audioNames.isNotEmpty())
        val pcm = readAssetPcm(testContext, audioNames.first())
        val prepare = prepareRuntime()

        val cold = createEngine()
        verifyOnStartWriteAndFinish(cold.engine, pcm, "prepared-cold")
        cold.engine.shutdown()
        val warm = createEngine()
        warm.engine.shutdown()

        SpeechRecognizeSdk.unloadModel()
        val modelReload = createEngine()
        verifyOnStartWriteAndFinish(modelReload.engine, pcm, "model-reload")
        modelReload.engine.shutdown()

        SpeechRecognizeSdk.unloadRuntime()
        assertEquals(0, SpeechRecognizeSdk.getLicenseInfo().status)
        val runtimePrepare = prepareRuntime()
        val runtimeReload = createEngine()
        verifyOnStartWriteAndFinish(runtimeReload.engine, pcm, "runtime-reload")
        runtimeReload.engine.shutdown()

        val report = mapOf(
            "case" to "runtime-fast-load",
            "prepareMs" to prepare.elapsedMs,
            "prepareBaselinePssKb" to prepare.baselinePssKb,
            "preparePeakPssKb" to prepare.peakPssKb,
            "preparePeakDeltaPssKb" to prepare.peakPssKb - prepare.baselinePssKb,
            "coldMs" to cold.elapsedMs,
            "coldPeakDeltaPssKb" to cold.peakPssKb - cold.baselinePssKb,
            "warmMs" to warm.elapsedMs,
            "modelReloadMs" to modelReload.elapsedMs,
            "modelReloadBaselinePssKb" to modelReload.baselinePssKb,
            "modelReloadPeakPssKb" to modelReload.peakPssKb,
            "modelReloadPeakDeltaPssKb" to
                modelReload.peakPssKb - modelReload.baselinePssKb,
            "runtimePrepareMs" to runtimePrepare.elapsedMs,
            "runtimePrepareBaselinePssKb" to runtimePrepare.baselinePssKb,
            "runtimePreparePeakPssKb" to runtimePrepare.peakPssKb,
            "runtimePreparePeakDeltaPssKb" to
                runtimePrepare.peakPssKb - runtimePrepare.baselinePssKb,
            "runtimeReloadMs" to runtimeReload.elapsedMs,
            "runtimeReloadPeakDeltaPssKb" to
                runtimeReload.peakPssKb - runtimeReload.baselinePssKb,
        )
        DqReport.append(targetContext, report)
        Log.i("DqRuntimeFastLoad", report.toString())
        assertTrue("SDK cold prepare should finish within 2000 ms", prepare.elapsedMs <= 2_000)
        assertTrue("model reload should finish within 2000 ms", modelReload.elapsedMs <= 2_000)
        assertTrue("runtime prepare should finish within 2000 ms", runtimePrepare.elapsedMs <= 2_000)
        assertTrue("prepared cold create should return within 300 ms", cold.elapsedMs <= 300)
        assertTrue("warm model reuse should return within 300 ms", warm.elapsedMs <= 300)
        assertTrue("prepared runtime create should return within 300 ms", runtimeReload.elapsedMs <= 300)
        assertTrue(
            "cold prepare PSS delta must stay within 600 MiB",
            prepare.peakPssKb - prepare.baselinePssKb <= MAX_COLD_LOAD_PEAK_DELTA_KB,
        )
        assertTrue(
            "model reload PSS delta must stay within 600 MiB",
            modelReload.peakPssKb - modelReload.baselinePssKb <= MAX_COLD_LOAD_PEAK_DELTA_KB,
        )
        assertTrue(
            "runtime prepare PSS delta must stay within 600 MiB",
            runtimePrepare.peakPssKb - runtimePrepare.baselinePssKb <=
                MAX_COLD_LOAD_PEAK_DELTA_KB,
        )
    }

    private fun activateValidLicense() {
        val path = stageRuntimeLicense(targetContext)
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

    private fun prepareRuntime(): PrepareTiming {
        val baselinePssKb = Debug.getPss()
        val peakPssKb = AtomicLong(baselinePssKb)
        val sampling = AtomicBoolean(true)
        val sampler = Thread({
            while (sampling.get()) {
                peakPssKb.getAndUpdate { previous -> maxOf(previous, Debug.getPss()) }
                SystemClock.sleep(50)
            }
        }, "runtime-pss-sampler").apply { start() }
        val start = SystemClock.elapsedRealtime()
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
        val completed = done.await(20, TimeUnit.SECONDS)
        val elapsedMs = SystemClock.elapsedRealtime() - start
        sampling.set(false)
        sampler.join(1_000)
        assertTrue("prepareRuntime callback timed out", completed)
        assertEquals("prepareRuntime failed", null, error)
        peakPssKb.getAndUpdate { previous -> maxOf(previous, Debug.getPss()) }
        return PrepareTiming(
            elapsedMs = elapsedMs,
            baselinePssKb = baselinePssKb,
            peakPssKb = peakPssKb.get(),
        )
    }

    private fun createEngine(): TimedEngine {
        val baselinePssKb = Debug.getPss()
        val peakPssKb = AtomicLong(baselinePssKb)
        val sampling = AtomicBoolean(true)
        val sampler = Thread({
            while (sampling.get()) {
                peakPssKb.getAndUpdate { previous -> maxOf(previous, Debug.getPss()) }
                SystemClock.sleep(50)
            }
        }, "engine-pss-sampler").apply { start() }
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
        val completed = done.await(120, TimeUnit.SECONDS)
        val elapsedMs = SystemClock.elapsedRealtime() - start
        sampling.set(false)
        sampler.join(1_000)
        assertTrue("createEngineAsync callback timed out", completed)
        assertEquals("createEngineAsync failed", null, error)
        assertNotNull(engine)
        peakPssKb.getAndUpdate { previous -> maxOf(previous, Debug.getPss()) }
        return TimedEngine(
            engine = engine!!,
            elapsedMs = elapsedMs,
            baselinePssKb = baselinePssKb,
            peakPssKb = peakPssKb.get(),
        )
    }

    private fun verifyOnStartWriteAndFinish(
        engine: SpeechRecognitionEngine,
        pcm: ByteArray,
        label: String,
    ) {
        val cached = pcm.copyOfRange(0, minOf(pcm.size, DQ_SR * 3))
        val sessionId = "$label-${System.currentTimeMillis()}"
        val listener = CapturingListener { startedSessionId ->
            feedFrames(engine, startedSessionId, cached, 0)
            engine.finish(startedSessionId)
        }
        engine.setListener(listener)
        engine.startListening(StartParams(sessionId, AudioInfo(), mapOf("vadEnd" to 800)))
        assertTrue("$label onStart write+finish did not return", listener.awaitStarted(20_000))
        assertTrue("$label session did not complete", listener.awaitComplete(30_000))
        awaitIdle(engine)
        assertEquals("$label must emit exactly one last", 1, listener.finals.count { it.isLast })
        assertEquals("$label must emit exactly one complete", 1, listener.completes.size)
        assertTrue("$label must not report errors: ${listener.errors}", listener.errors.isEmpty())
        assertTrue(
            "$label cold/reloaded stream must recognize the 1.5 s command prefix",
            listener.finalText().isNotBlank(),
        )
    }

    private data class TimedEngine(
        val engine: SpeechRecognitionEngine,
        val elapsedMs: Long,
        val baselinePssKb: Long,
        val peakPssKb: Long,
    )

    private data class PrepareTiming(
        val elapsedMs: Long,
        val baselinePssKb: Long,
        val peakPssKb: Long,
    )

    private companion object {
        const val MAX_COLD_LOAD_PEAK_DELTA_KB: Long = 600L * 1024
    }
}
