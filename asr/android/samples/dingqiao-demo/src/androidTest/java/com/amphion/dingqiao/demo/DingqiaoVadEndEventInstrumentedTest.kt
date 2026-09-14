package com.amphion.dingqiao.demo

import android.content.Intent
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.AudioInfo
import com.amphion.dingqiao.CreateEngineParams
import com.amphion.dingqiao.DingqiaoEventCode
import com.amphion.dingqiao.DingqiaoOnlineMode
import com.amphion.dingqiao.RecognitionListener
import com.amphion.dingqiao.SpeechRecognitionResult
import com.amphion.dingqiao.SpeechRecognizeSdk
import com.amphion.dingqiao.StartParams
import java.io.File
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Public Dingqiao callback gate for 20 ms caller frames and an 800 ms tail-silence setting. */
@RunWith(AndroidJUnit4::class)
class DingqiaoVadEndEventInstrumentedTest {
    @Test
    fun speechEndCanDriveFinishBeforeMaxDuration() = runScenario("short")

    @Test
    fun longModeSpeechEndCanDriveFinishWithLowNoise() = runScenario("long")

    private fun runScenario(recognizerMode: String) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val runStartedAtMs = SystemClock.elapsedRealtime()
        val report = File(
            context.filesDir,
            "vad_end_event_${recognizerMode}_noise_report.txt",
        )
        // Vivo freezes a background instrumentation process and stretches 4 seconds of PCM
        // submission into minutes. Keep the tested app foreground without touching the SDK.
        context.startActivity(
            Intent(context, DeviceTestKeepAliveActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
        SystemClock.sleep(500)
        prepareSdkRuntime(context, File(context.getExternalFilesDir(null), "vad_end_event_work"))
        val engine = SpeechRecognizeSdk.createEngine(
            CreateEngineParams(
                language = "zh-CN",
                online = DingqiaoOnlineMode.OFFLINE,
                extraParams = mapOf("recognizerMode" to recognizerMode),
            ),
        )
        val sessionId = "vad-end-event-${System.currentTimeMillis()}"
        val started = CountDownLatch(1)
        val ended = CountDownLatch(1)
        val completed = CountDownLatch(1)
        val finishInvoked = AtomicBoolean(false)
        val trace = Collections.synchronizedList(mutableListOf<String>())
        val errors = Collections.synchronizedList(mutableListOf<String>())
        var beginCount = 0
        var endCount = 0
        var lastCount = 0
        var completeCount = 0
        var nonemptyFinalCount = 0
        var nonemptyPartialCount = 0
        val startAtMs = AtomicLong(0L)
        val feedStartMs = AtomicLong(0L)
        val endAtMs = AtomicLong(0L)
        val completeAtMs = AtomicLong(0L)
        val tailStartMs = AtomicLong(0L)

        try {
            engine.setListener(object : RecognitionListener {
                override fun onStart(sessionId: String, eventMessage: String) {
                    startAtMs.set(SystemClock.elapsedRealtime())
                    trace.add("start")
                    started.countDown()
                }

                override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) {
                    when (eventCode) {
                        DingqiaoEventCode.SPEECH_BEGIN -> {
                            synchronized(trace) { beginCount++ }
                            trace.add("begin")
                        }
                        DingqiaoEventCode.SPEECH_END -> {
                            synchronized(trace) { endCount++ }
                            endAtMs.set(SystemClock.elapsedRealtime())
                            trace.add("end")
                            if (finishInvoked.compareAndSet(false, true)) engine.finish(sessionId)
                            ended.countDown()
                        }
                    }
                }

                override fun onResult(sessionId: String, result: SpeechRecognitionResult) {
                    if (!result.isFinal) {
                        if (result.result.isNotBlank()) synchronized(trace) { nonemptyPartialCount++ }
                        return
                    }
                    synchronized(trace) {
                        if (result.result.isNotBlank()) nonemptyFinalCount++
                        if (result.isLast) lastCount++
                        trace.add(if (result.isLast) "last" else "final")
                    }
                }

                override fun onComplete(sessionId: String, eventMessage: String) {
                    synchronized(trace) { completeCount++ }
                    completeAtMs.set(SystemClock.elapsedRealtime())
                    trace.add("complete")
                    completed.countDown()
                }

                override fun onError(sessionId: String, errorCode: Int, errorMessage: String) {
                    errors.add("$errorCode:$errorMessage")
                    trace.add("error")
                    completed.countDown()
                }
            })
            engine.startListening(
                StartParams(
                    sessionId,
                    AudioInfo(),
                    mapOf(
                        "recognizerMode" to recognizerMode,
                        "vadEnd" to 800,
                        "maxAudioDuration" to 20_000,
                        "enablePartialResult" to true,
                    ),
                ),
            )
            assertTrue("start timed out: $errors", started.await(20, TimeUnit.SECONDS))

            val pcm = DqWav.read16kMonoPcm(
                "001_recognize.wav",
                instrumentation.context.assets.open("001_recognize.wav").use { it.readBytes() },
            )
            // Fixed speech and deterministic low-amplitude noise (PCM16 <= 50), written with
            // the public Dingqiao API's required 20 ms / 640-byte caller frame size.
            feedStartMs.set(SystemClock.elapsedRealtime())
            val speech = pcm.copyOfRange(0, DQ_SR * 2 * 4)
            feedRealtime(engine, sessionId, speech, finishInvoked)
            tailStartMs.set(SystemClock.elapsedRealtime())
            val tail = lowNoisePcm(3)
            feedRealtime(engine, sessionId, tail, finishInvoked)

            assertTrue(
                "SPEECH_END did not drive finish: $trace $errors",
                ended.await(2, TimeUnit.SECONDS),
            )
            assertTrue("SPEECH_END did not invoke finish: $trace", finishInvoked.get())
            val endDelayMs = endAtMs.get() - tailStartMs.get()
            assertTrue("SPEECH_END must follow the supplied silence: $trace", endDelayMs >= 0)
            assertTrue("SPEECH_END was too late after silence ($endDelayMs ms): $trace", endDelayMs < 1_800)
            assertTrue("completion timed out: $trace $errors", completed.await(10, TimeUnit.SECONDS))
            assertTrue("unexpected SDK errors: $errors", errors.isEmpty())
            synchronized(trace) {
                assertTrue("missing confirmed speech: $trace", nonemptyFinalCount > 0)
                assertEquals("SPEECH_BEGIN count: $trace", 1, beginCount)
                assertEquals("SPEECH_END count: $trace", 1, endCount)
                assertEquals("isLast count: $trace", 1, lastCount)
                assertEquals("onComplete count: $trace", 1, completeCount)
                assertTrue("last must precede complete: $trace", trace.indexOf("last") < trace.indexOf("complete"))
                assertFalse("max duration ended before the caller's finish: $trace", trace.indexOf("last") < trace.indexOf("end"))
            }
        } finally {
            val shutdownStartedAtMs = SystemClock.elapsedRealtime()
            report.writeText(
                "startMs=${startAtMs.get() - runStartedAtMs}\n" +
                    "feedStartMs=${feedStartMs.get() - runStartedAtMs}\n" +
                    "tailStartMs=${tailStartMs.get() - runStartedAtMs}\n" +
                    "speechEndMs=${endAtMs.get() - runStartedAtMs}\n" +
                    "endDelayMs=${endAtMs.get() - tailStartMs.get()}\n" +
                    "completeMs=${completeAtMs.get() - runStartedAtMs}\n" +
                    "beforeShutdownMs=${shutdownStartedAtMs - runStartedAtMs}\n" +
                    "beginCount=$beginCount endCount=$endCount lastCount=$lastCount " +
                    "completeCount=$completeCount nonemptyPartialCount=$nonemptyPartialCount " +
                    "nonemptyFinalCount=$nonemptyFinalCount\n" +
                    "trace=${trace.joinToString(",")}\n",
                Charsets.UTF_8,
            )
            engine.shutdown()
            report.appendText(
                "shutdownMs=${SystemClock.elapsedRealtime() - shutdownStartedAtMs}\n",
                Charsets.UTF_8,
            )
        }
    }

    private fun feedRealtime(
        engine: com.amphion.dingqiao.SpeechRecognitionEngine,
        sessionId: String,
        pcm: ByteArray,
        finished: AtomicBoolean,
    ) {
        var offset = 0
        while (offset < pcm.size && !finished.get()) {
            val frame = ByteArray(DQ_FRAME)
            val size = minOf(frame.size, pcm.size - offset)
            System.arraycopy(pcm, offset, frame, 0, size)
            engine.writeAudio(sessionId, frame)
            offset += size
            Thread.sleep(DQ_FRAME_MS)
        }
    }

    private fun lowNoisePcm(seconds: Int): ByteArray {
        val pcm = ByteArray(DQ_SR * 2 * seconds)
        var seed = 1
        for (index in 0 until pcm.size / 2) {
            seed = seed * 1_103_515_245 + 12_345
            val sample = (seed ushr 16) % 101 - 50
            pcm[index * 2] = sample.toByte()
            pcm[index * 2 + 1] = (sample shr 8).toByte()
        }
        return pcm
    }
}
