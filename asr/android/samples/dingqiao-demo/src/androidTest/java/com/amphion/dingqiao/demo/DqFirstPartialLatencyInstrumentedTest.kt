package com.amphion.dingqiao.demo

import android.os.SystemClock
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.AudioInfo
import com.amphion.dingqiao.CreateEngineParams
import com.amphion.dingqiao.RecognitionListener
import com.amphion.dingqiao.SpeechRecognitionResult
import com.amphion.dingqiao.SpeechRecognizeSdk
import com.amphion.dingqiao.StartParams
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class DqFirstPartialLatencyInstrumentedTest {
    @Test
    fun pacedPcmReportsWallAndAudioTimeAtFirstNonEmptyPartial() {
        val target = InstrumentationRegistry.getInstrumentation().targetContext
        val test = InstrumentationRegistry.getInstrumentation().context
        prepareSdkRuntime(test, target, File(target.filesDir, "first-partial-latency"))
        val engine = SpeechRecognizeSdk.createEngine(CreateEngineParams(language = "zh-CN"))
        val pcm = readAssetPcm(test, mainWavs(test).first())
        val started = CountDownLatch(1)
        val firstPartial = CountDownLatch(1)
        val completed = CountDownLatch(1)
        val firstPcmElapsedMs = AtomicLong(-1L)
        val firstPartialElapsedMs = AtomicLong(-1L)
        val framesWrittenAtFirstPartial = AtomicInteger(-1)
        val framesWritten = AtomicInteger(0)
        val errors = mutableListOf<String>()

        engine.setListener(object : RecognitionListener {
            override fun onStart(sessionId: String, eventMessage: String) {
                started.countDown()
            }

            override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) = Unit

            override fun onResult(sessionId: String, result: SpeechRecognitionResult) {
                if (!result.isFinal && result.result.isNotBlank()) {
                    val now = SystemClock.elapsedRealtime()
                    if (firstPartialElapsedMs.compareAndSet(-1L, now)) {
                        framesWrittenAtFirstPartial.set(framesWritten.get())
                        firstPartial.countDown()
                    }
                }
            }

            override fun onComplete(sessionId: String, eventMessage: String) {
                completed.countDown()
            }

            override fun onError(sessionId: String, errorCode: Int, errorMessage: String) {
                errors += "$errorCode $errorMessage"
                completed.countDown()
            }
        })

        val sessionId = "first-partial-${System.currentTimeMillis()}"
        engine.startListening(
            StartParams(
                sessionId,
                AudioInfo(),
                extraParams = mapOf("enablePartialResult" to true, "vadEnd" to 800),
            ),
        )
        assertTrue("onStart timed out", started.await(20, TimeUnit.SECONDS))

        firstPcmElapsedMs.set(SystemClock.elapsedRealtime())
        var offset = 0
        while (offset < pcm.size) {
            val frame = ByteArray(DQ_FRAME)
            val size = minOf(DQ_FRAME, pcm.size - offset)
            System.arraycopy(pcm, offset, frame, 0, size)
            engine.writeAudio(sessionId, frame)
            framesWritten.incrementAndGet()
            offset += size
            Thread.sleep(DQ_FRAME_MS)
        }
        feedSilence(engine, sessionId, 1_000)
        engine.finish(sessionId)
        assertTrue("session did not complete: $errors", completed.await(30, TimeUnit.SECONDS))
        assertTrue("first non-empty partial was not emitted: $errors", firstPartial.await(1, TimeUnit.SECONDS))

        val wallMs = firstPartialElapsedMs.get() - firstPcmElapsedMs.get()
        val audioMs = framesWrittenAtFirstPartial.get() * DQ_FRAME_MS
        val report = mapOf(
            "case" to "first-partial-latency",
            "wallMs" to wallMs,
            "audioFedAtCallbackMs" to audioMs,
            "wallMinusAudioMs" to wallMs - audioMs,
            "pcmDurationMs" to pcm.size * 1000L / (DQ_SR * 2L),
        )
        DqReport.append(target, report)
        Log.i("DqFirstPartialLatency", report.toString())
        assertTrue("first partial wall latency must be non-negative: $report", wallMs >= 0L)
        assertTrue("first partial must follow accepted audio: $report", audioMs > 0L)
        engine.shutdown()
    }
}
