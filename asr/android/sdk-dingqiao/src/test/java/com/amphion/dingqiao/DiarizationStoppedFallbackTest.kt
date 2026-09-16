package com.amphion.dingqiao

import android.content.Context
import com.amphion.asr.*
import com.amphion.dingqiao.diarization.SpeakerDiarizationLocalClient
import com.amphion.dingqiao.diarization.SpeakerDiarizationSession
import org.junit.Assert.*
import org.junit.Test
import org.mockito.Mockito.mockConstruction
import org.mockito.kotlin.*
import java.util.concurrent.*

class DiarizationStoppedFallbackTest {
    @Test fun stoppedFallbackCannotReplaceRealTailWhileSpeakerWorkIsPending() = runSequence("最后一句")
    @Test fun stoppedFallbackStillCompletesWhenNoAsrTailWasProduced() = runSequence(null)

    private fun runSequence(tail: String?) {
        mockConstruction(SpeakerDiarizationLocalClient::class.java).use {
            val asr = mock<AsrEngine>()
            val nativeSession = mock<AsrSession>()
            lateinit var callback: AsrCallback
            whenever(asr.newSession(any(), any())).thenAnswer { call ->
                callback = call.getArgument(0); nativeSession
            }
            val callbacks = Executors.newSingleThreadExecutor()
            val directory = kotlin.io.path.createTempDirectory().toFile()
            val engine = DingqiaoRecognitionEngine(mock<Context>(), CreateEngineParams(),
                VoiceprintStore(directory), null, callbacks, {}, asr, { it })
            val scheduler = engine.javaClass.getDeclaredField("stopFallbackExecutor")
                .apply { isAccessible = true }.get(null) as ScheduledExecutorService
            val results = CopyOnWriteArrayList<SpeechRecognitionResult>()
            val events = CopyOnWriteArrayList<String>()
            val completed = CountDownLatch(1)
            engine.setListener(object : RecognitionListener {
                override fun onStart(sessionId: String, eventMessage: String) = Unit
                override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) = Unit
                override fun onResult(sessionId: String, result: SpeechRecognitionResult) {
                    results += result; events += "last"
                }
                override fun onSpeakerDiarizationResult(sessionId: String, result: SpeakerDiarizationResult) { events += "roles" }
                override fun onComplete(sessionId: String, eventMessage: String) { events += "complete"; completed.countDown() }
                override fun onError(sessionId: String, errorCode: Int, errorMessage: String) { events += "error" }
            })
            try {
                engine.startListening(StartParams("s", speakerDiarization = SpeakerDiarizationConfig()))
                val controller = engine.javaClass.getDeclaredField("speakerDiarizationSession")
                    .apply { isAccessible = true }.get(engine) as SpeakerDiarizationSession
                engine.writeAudio("s", ByteArray(640))
                engine.finish("s")
                if (tail != null) callback.onFinal(AsrResult(text = tail, rawText = tail, isLast = true))
                callback.onSessionStopped()
                scheduler.schedule({}, 1600, TimeUnit.MILLISECONDS).get(5, TimeUnit.SECONDS)
                assertTrue("must wait for the speaker tail", results.isEmpty())
                controller.onDrained()
                assertTrue(completed.await(5, TimeUnit.SECONDS))
                assertEquals(tail ?: "", results.single().result)
                assertTrue(results.single().isLast)
                assertEquals(listOf("last", "roles", "complete"), events.toList())
            } finally {
                engine.shutdown(); callbacks.shutdownNow(); directory.deleteRecursively()
            }
        }
    }
}
