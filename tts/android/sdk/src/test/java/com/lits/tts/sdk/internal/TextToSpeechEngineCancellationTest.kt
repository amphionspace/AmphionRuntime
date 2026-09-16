package com.lits.tts.sdk.internal

import com.lits.tts.sdk.CompleteResponse
import com.lits.tts.sdk.CreateEngineParams
import com.lits.tts.sdk.PlayType
import com.lits.tts.sdk.QueueMode
import com.lits.tts.sdk.RunMode
import com.lits.tts.sdk.SpeakListener
import com.lits.tts.sdk.SpeakParams
import com.lits.tts.sdk.StartResponse
import com.lits.tts.sdk.StopResponse
import com.lits.tts.sdk.SynthesisResponse
import com.lits.tts.sdk.VoiceInfo
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertEquals
import java.util.concurrent.CopyOnWriteArrayList
import org.junit.Test

class TextToSpeechEngineCancellationTest {
    @Test fun internalCancellationStillReportsTheUnderlyingError() {
        val dispatched = CountDownLatch(2)
        val events = CopyOnWriteArrayList<String>()
        lateinit var engine: TextToSpeechEngineImpl
        val synth = object : PcmSynthesizer {
            override fun preload() = Unit
            override fun supportsInternalPlayback() = false
            override fun synthesize(text: String, params: SpeakParams, engineParams: CreateEngineParams): SynthesizedAudio {
                // AndroidPcmPlayer stops its peer worker with this shared flag on
                // internal failure. It does not set the user's stopRequested flag.
                val task = engine.javaClass.getDeclaredField("current").apply { isAccessible = true }.get(engine)
                val flag = task.javaClass.getDeclaredField("cancelled").apply { isAccessible = true }.get(task)
                (flag as java.util.concurrent.atomic.AtomicBoolean).set(true)
                throw IllegalStateException("internal playback failure")
            }
        }
        engine = TextToSpeechEngineImpl(CreateEngineParams("zh-en", RunMode.OFFLINE, "lits-female-02"),
            VoiceInfo("zh-en", "lits-female-02", "female"), null, null, { true }, synth,
            java.util.concurrent.Executor { try { it.run() } finally { dispatched.countDown() } })
        engine.setListener(object : SpeakListener {
            override fun onStart(requestId: String, response: StartResponse) { events += "START" }
            override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) = Unit
            override fun onComplete(requestId: String, response: CompleteResponse) { events += "COMPLETE" }
            override fun onStop(requestId: String, response: StopResponse) { events += "STOP" }
            override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
                events += "ERROR"
                assertEquals("internal playback failure", errorMessage)
                engine.shutdown()
            }
        })
        try {
            engine.speak("内部错误。", SpeakParams("internal-error", playType = PlayType.SYNTHESIZE_ONLY))
            assertTrue(dispatched.await(2, TimeUnit.SECONDS))
            assertEquals(listOf("START", "ERROR"), events.toList())
        } finally { runCatching { engine.shutdown() } }
    }

    @Test fun terminalCallbacksCommitBeforeReentrantStopOrShutdown() {
        for (playType in listOf(PlayType.SYNTHESIZE_ONLY, PlayType.SYNTHESIZE_AND_PLAY)) {
            for (action in listOf("stop", "shutdown")) {
                val closed = CountDownLatch(1)
                val done = CountDownLatch(1)
                val events = CopyOnWriteArrayList<String>()
                val synth = object : PcmSynthesizer {
                    override fun preload() = Unit
                    override fun supportsInternalPlayback() = false
                    override fun synthesize(text: String, params: SpeakParams, engineParams: CreateEngineParams) =
                        SynthesizedAudio(byteArrayOf(1, 0), 24000)
                    override fun close(releaseSharedResources: Boolean) { closed.countDown() }
                }
                val engine = TextToSpeechEngineImpl(
                    CreateEngineParams("zh-en", RunMode.OFFLINE, "lits-female-02"),
                    VoiceInfo("zh-en", "lits-female-02", "female"), null, null, { true }, synth,
                    // Exercise completion before worker-finally without relying on thread timing.
                    java.util.concurrent.Executor { it.run() },
                )
                engine.setListener(object : SpeakListener {
                    override fun onStart(requestId: String, response: StartResponse) = Unit
                    override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) = Unit
                    override fun onComplete(requestId: String, response: CompleteResponse) {
                        events += response.type.name
                        if (playType == PlayType.SYNTHESIZE_ONLY || response.type == com.lits.tts.sdk.CompleteType.PLAYBACK_COMPLETE) {
                            if (action == "stop") engine.stop() else engine.shutdown()
                            done.countDown()
                        }
                    }
                    override fun onStop(requestId: String, response: StopResponse) { events += "STOP" }
                    override fun onError(requestId: String, errorCode: Int, errorMessage: String) { events += "ERROR"; done.countDown() }
                })
                try {
                    engine.speak("完成回调内释放。", SpeakParams("terminal", playType = playType))
                    assertTrue(done.await(2, TimeUnit.SECONDS))
                } finally { runCatching { engine.shutdown() } }
                assertTrue(closed.await(2, TimeUnit.SECONDS))
                assertEquals("$playType/$action", if (playType == PlayType.SYNTHESIZE_ONLY)
                    listOf("SYNTHESIS_COMPLETE") else listOf("SYNTHESIS_COMPLETE", "PLAYBACK_COMPLETE"), events.toList())
            }
        }
    }

    @Test fun errorCallbackCanShutdownWithoutAStopAfterError() {
        val closed = CountDownLatch(1)
        val events = CopyOnWriteArrayList<String>()
        val synth = object : PcmSynthesizer {
            override fun preload() = Unit
            override fun supportsInternalPlayback() = false
            override fun synthesize(text: String, params: SpeakParams, engineParams: CreateEngineParams): SynthesizedAudio =
                throw IllegalStateException("genuine error")
            override fun close(releaseSharedResources: Boolean) { closed.countDown() }
        }
        val engine = TextToSpeechEngineImpl(CreateEngineParams("zh-en", RunMode.OFFLINE, "lits-female-02"),
            VoiceInfo("zh-en", "lits-female-02", "female"), null, null, { true }, synth, java.util.concurrent.Executor { it.run() })
        engine.setListener(object : SpeakListener {
            override fun onStart(requestId: String, response: StartResponse) = Unit
            override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) = Unit
            override fun onComplete(requestId: String, response: CompleteResponse) { events += "COMPLETE" }
            override fun onStop(requestId: String, response: StopResponse) { events += "STOP" }
            override fun onError(requestId: String, errorCode: Int, errorMessage: String) { events += "ERROR"; engine.shutdown() }
        })
        engine.speak("错误回调内释放。", SpeakParams("error", playType = PlayType.SYNTHESIZE_ONLY))
        assertTrue(closed.await(2, TimeUnit.SECONDS))
        assertEquals(listOf("ERROR"), events.toList())
    }

    @Test fun synthesisCompletionDuringPlaybackIsNotTerminalAndCanStillBeStopped() {
        val closed = CountDownLatch(1)
        val stopped = CountDownLatch(1)
        val events = CopyOnWriteArrayList<String>()
        val synth = object : PcmSynthesizer {
            override fun preload() = Unit
            override fun supportsInternalPlayback() = false
            override fun synthesize(text: String, params: SpeakParams, engineParams: CreateEngineParams) = SynthesizedAudio(byteArrayOf(1, 0), 24000)
            override fun close(releaseSharedResources: Boolean) { closed.countDown() }
        }
        val engine = TextToSpeechEngineImpl(CreateEngineParams("zh-en", RunMode.OFFLINE, "lits-female-02"),
            VoiceInfo("zh-en", "lits-female-02", "female"), null, null, { true }, synth, java.util.concurrent.Executor { it.run() })
        engine.setListener(object : SpeakListener {
            override fun onStart(requestId: String, response: StartResponse) = Unit
            override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) = Unit
            override fun onComplete(requestId: String, response: CompleteResponse) { events += response.type.name; engine.stop() }
            override fun onStop(requestId: String, response: StopResponse) { events += "STOP"; stopped.countDown() }
        })
        try {
            engine.speak("合成完成仍可停止播放。", SpeakParams("play", playType = PlayType.SYNTHESIZE_AND_PLAY))
            assertTrue(stopped.await(2, TimeUnit.SECONDS))
        } finally { engine.shutdown() }
        assertTrue(closed.await(2, TimeUnit.SECONDS))
        assertEquals(listOf("SYNTHESIS_COMPLETE", "STOP"), events.toList())
    }

    @Test
    fun shutdownDefersCloseUntilInFlightNativeWorkReturns() {
        val entered = CountDownLatch(1)
        val finish = CountDownLatch(1)
        val closed = CountDownLatch(1)
        val synth = object : PcmSynthesizer {
            override fun preload() = Unit
            override fun supportsInternalPlayback() = false
            override fun synthesize(text: String, params: SpeakParams, engineParams: CreateEngineParams): SynthesizedAudio {
                entered.countDown()
                // JNI inference does not return just because Java interrupts its thread.
                while (finish.count > 0) {
                    try { finish.await() } catch (_: InterruptedException) { }
                }
                return SynthesizedAudio(ByteArray(0), 24000)
            }
            override fun close(releaseSharedResources: Boolean) { closed.countDown() }
        }
        val engine = testEngine(synth)
        engine.setListener(StartLatchListener("unused"))
        try {
            engine.speak("关闭时还在推理。", SpeakParams("active", playType = PlayType.SYNTHESIZE_ONLY))
            assertTrue(entered.await(2, TimeUnit.SECONDS))
            engine.shutdown()
            assertFalse("native resources must remain alive", closed.await(100, TimeUnit.MILLISECONDS))
        } finally {
            finish.countDown()
        }
        assertTrue("release after worker exits", closed.await(2, TimeUnit.SECONDS))
    }

    @Test
    fun cancelledWorkerErrorDoesNotFollowStopButRealErrorStillReports() {
        val entered = CountDownLatch(1)
        val finish = CountDownLatch(1)
        val events = CopyOnWriteArrayList<String>()
        val genuineError = CountDownLatch(1)
        val synth = object : PcmSynthesizer {
            override fun preload() = Unit
            override fun supportsInternalPlayback() = false
            override fun synthesize(text: String, params: SpeakParams, engineParams: CreateEngineParams): SynthesizedAudio {
                if (params.requestId == "cancelled") {
                    entered.countDown()
                    finish.await()
                }
                throw IllegalStateException("test synthesis failure")
            }
        }
        val engine = testEngine(synth)
        engine.setListener(object : SpeakListener {
            override fun onStart(requestId: String, response: StartResponse) = Unit
            override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) { events += "data:$requestId" }
            override fun onComplete(requestId: String, response: CompleteResponse) { events += "complete:$requestId" }
            override fun onStop(requestId: String, response: StopResponse) { events += "stop:$requestId" }
            override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
                events += "error:$requestId"
                if (requestId == "genuine") genuineError.countDown()
            }
        })
        try {
            engine.speak("取消。", SpeakParams("cancelled", playType = PlayType.SYNTHESIZE_ONLY))
            assertTrue(entered.await(2, TimeUnit.SECONDS))
            engine.stop()
            finish.countDown()
            // A queued task creates a callback barrier after the old worker unwinds.
            Thread.sleep(100)
            engine.speak("实际错误。", SpeakParams("genuine", playType = PlayType.SYNTHESIZE_ONLY))
            assertTrue(genuineError.await(2, TimeUnit.SECONDS))
            assertEquals(listOf("stop:cancelled", "error:genuine"), events.toList())
        } finally {
            finish.countDown()
            engine.shutdown()
        }
    }

    private fun testEngine(synthesizer: PcmSynthesizer) = TextToSpeechEngineImpl(
        CreateEngineParams("zh-en", RunMode.OFFLINE, "lits-female-02"),
        VoiceInfo("zh-en", "lits-female-02", "female"), null, null, { true }, synthesizer,
    )

    @Test
    fun stopLetsNextPreemptRequestStartWithoutWaitingForLongStreamingSynthesis() {
        val synthesizer = SlowStreamingSynthesizer(checkCancellation = true)
        val engine = TextToSpeechEngineImpl(
            engineParams = CreateEngineParams("zh-en", RunMode.OFFLINE, "lits-female-02"),
            voice = VoiceInfo("zh-en", "lits-female-02", "female"),
            engineName = null,
            workPath = null,
            onRelease = { true },
            synthesizer = synthesizer,
        )
        val listener = StartLatchListener(newRequestId = "new")
        engine.setListener(listener)

        engine.speak(
            "这是一段超过一百个字的长文本，用来模拟用户先播放，然后停止，然后再次播放时，旧的流式合成仍然在后台继续执行的情况。".repeat(3),
            SpeakParams(requestId = "old", playType = PlayType.SYNTHESIZE_ONLY),
        )
        assertTrue(listener.oldStarted.await(1, TimeUnit.SECONDS))

        engine.stop()
        engine.speak(
            "新的请求应该很快开始。",
            SpeakParams(requestId = "new", playType = PlayType.SYNTHESIZE_ONLY, queueMode = QueueMode.PREEMPT),
        )

        assertTrue(
            "new request should not wait for the cancelled long streaming synthesis to finish",
            listener.newStarted.await(300, TimeUnit.MILLISECONDS),
        )

        engine.shutdown()
    }

    @Test
    fun preemptStartsNextRequestEvenIfCancelledStreamingProducerHasNotReturned() {
        val synthesizer = SlowStreamingSynthesizer(checkCancellation = false)
        val engine = TextToSpeechEngineImpl(
            engineParams = CreateEngineParams("zh-en", RunMode.OFFLINE, "lits-female-02"),
            voice = VoiceInfo("zh-en", "lits-female-02", "female"),
            engineName = null,
            workPath = null,
            onRelease = { true },
            synthesizer = synthesizer,
        )
        val listener = StartLatchListener(newRequestId = "new")
        engine.setListener(listener)

        engine.speak(
            "这是一段没有标点也没有空格的极端长句".repeat(12),
            SpeakParams(requestId = "old", playType = PlayType.SYNTHESIZE_ONLY),
        )
        assertTrue(listener.oldStarted.await(1, TimeUnit.SECONDS))
        assertFalse(synthesizer.producerReturned.await(80, TimeUnit.MILLISECONDS))

        engine.speak(
            "新的请求应该不等待旧 producer 返回。",
            SpeakParams(requestId = "new", playType = PlayType.SYNTHESIZE_ONLY, queueMode = QueueMode.PREEMPT),
        )

        assertTrue(
            "new request should start even while the cancelled old streaming producer is still unwinding",
            listener.newStarted.await(300, TimeUnit.MILLISECONDS),
        )

        engine.shutdown()
    }

    private class SlowStreamingSynthesizer(private val checkCancellation: Boolean) : PcmSynthesizer {
        val producerReturned = CountDownLatch(1)

        override fun preload() = Unit

        override fun supportsStreamingSynthesis(): Boolean = true

        override fun supportsInternalPlayback(): Boolean = false

        override fun streamingSampleRate(engineParams: CreateEngineParams): Int = 24_000

        override fun synthesize(text: String, params: SpeakParams, engineParams: CreateEngineParams): SynthesizedAudio {
            return SynthesizedAudio(ByteArray(0), sampleRate = 24_000)
        }

        override fun synthesizeStreaming(
            text: String,
            params: SpeakParams,
            engineParams: CreateEngineParams,
            collectOutput: Boolean,
            isCancelled: () -> Boolean,
            onChunk: (ByteArray) -> Unit,
        ): SynthesizedAudio {
            try {
                repeat(100) {
                    if (checkCancellation && isCancelled()) {
                        return SynthesizedAudio(ByteArray(0), sampleRate = 24_000)
                    }
                    Thread.sleep(20)
                    if (checkCancellation && isCancelled()) {
                        return SynthesizedAudio(ByteArray(0), sampleRate = 24_000)
                    }
                    onChunk(byteArrayOf(0, 0))
                }
                return SynthesizedAudio(ByteArray(0), sampleRate = 24_000)
            } finally {
                producerReturned.countDown()
            }
        }
    }

    private class StartLatchListener(private val newRequestId: String) : SpeakListener {
        val oldStarted = CountDownLatch(1)
        val newStarted = CountDownLatch(1)

        override fun onStart(requestId: String, response: StartResponse) {
            if (requestId == "old") oldStarted.countDown()
            if (requestId == newRequestId) newStarted.countDown()
        }

        override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) = Unit

        override fun onComplete(requestId: String, response: CompleteResponse) = Unit

        override fun onStop(requestId: String, response: StopResponse) = Unit
    }
}
