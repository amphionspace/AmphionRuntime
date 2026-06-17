package com.lits.tts.sdk

import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TextToSpeechSdkTest {
    private val primaryVoiceId = "lits-female-01"
    private val secondaryVoiceId = "lits-female-02"
    private val engines = mutableListOf<TextToSpeechEngine>()

    @After
    fun tearDown() {
        engines.forEach { engine ->
            runCatching { engine.shutdown() }
        }
        engines.clear()
    }

    @Test
    fun listVoicesReturnsSharedVoiceIdsAcrossLanguages() {
        val voices = TextToSpeechSdk.listVoices(
            VoiceQuery(requestId = "voices-1", mode = RunMode.OFFLINE),
        )

        assertEquals(4, voices.size)
        assertEquals(setOf("zh-en", "en-US"), voices.map { it.language }.toSet())
        assertEquals(setOf(primaryVoiceId, secondaryVoiceId), voices.map { it.voiceId }.toSet())
        assertEquals(
            setOf(primaryVoiceId, secondaryVoiceId),
            voices.filter { it.language == "zh-en" }.map { it.voiceId }.toSet(),
        )
        assertEquals(
            setOf(primaryVoiceId, secondaryVoiceId),
            voices.filter { it.language == "en-US" }.map { it.voiceId }.toSet(),
        )
    }

    @Test
    fun listVoicesCallbackRunsAsynchronously() {
        val callerThread = Thread.currentThread().name
        val callbackThread = AtomicReference<String>()
        val voicesResult = AtomicReference<List<VoiceInfo>>()
        val latch = CountDownLatch(1)

        TextToSpeechSdk.listVoices(
            VoiceQuery(requestId = "voices-callback", mode = RunMode.OFFLINE),
            object : Callback<List<VoiceInfo>> {
                override fun onSuccess(result: List<VoiceInfo>) {
                    callbackThread.set(Thread.currentThread().name)
                    voicesResult.set(result)
                    latch.countDown()
                }

                override fun onError(errorCode: Int, errorMessage: String) {
                    throw AssertionError("Unexpected listVoices error: $errorCode $errorMessage")
                }
            },
        )

        assertTrue(latch.await(5, TimeUnit.SECONDS))
        assertEquals(4, voicesResult.get().size)
        assertEquals(setOf("zh-en", "en-US"), voicesResult.get().map { it.language }.toSet())
        assertEquals(setOf(primaryVoiceId, secondaryVoiceId), voicesResult.get().map { it.voiceId }.toSet())
        assertNotEquals(callerThread, callbackThread.get())
    }

    @Test
    fun listVoicesRejectsBlankRequestId() {
        val error = expectTtsException {
            TextToSpeechSdk.listVoices(
                VoiceQuery(requestId = " ", mode = RunMode.OFFLINE),
            )
        }

        assertEquals(TtsErrorCode.RUNTIME_EXCEPTION, error.errorCode)
    }

    @Test
    fun createEngineRejectsUnsupportedLanguage() {
        val error = expectTtsException {
            TextToSpeechSdk.createEngine(
                CreateEngineParams(
                    language = "zh-CN",
                    mode = RunMode.OFFLINE,
                    voiceId = primaryVoiceId,
                ),
            )
        }

        assertEquals(TtsErrorCode.LANGUAGE_UNSUPPORTED, error.errorCode)
    }

    @Test
    fun createEngineAcceptsCustomLocateString() {
        val engine = TextToSpeechSdk.createEngine(
            CreateEngineParams(
                language = "zh-en",
                mode = RunMode.OFFLINE,
                voiceId = primaryVoiceId,
                locate = "SG",
            ),
        )

        engines += engine
    }

    @Test
    fun createEngineRejectsBlankEngineName() {
        val error = expectTtsException {
            TextToSpeechSdk.createEngine(
                CreateEngineParams(
                    language = "zh-en",
                    mode = RunMode.OFFLINE,
                    voiceId = primaryVoiceId,
                    engineName = " ",
                ),
            )
        }

        assertEquals(TtsErrorCode.CREATE_ENGINE_FAILED, error.errorCode)
    }

    @Test
    fun createEngineRejectsBlankLocate() {
        val error = expectTtsException {
            TextToSpeechSdk.createEngine(
                CreateEngineParams(
                    language = "zh-en",
                    mode = RunMode.OFFLINE,
                    voiceId = primaryVoiceId,
                    locate = " ",
                ),
            )
        }

        assertEquals(TtsErrorCode.CREATE_ENGINE_FAILED, error.errorCode)
    }

    @Test
    fun createEngineSupportsSameVoiceIdAcrossLanguages() {
        val mixedEngine = TextToSpeechSdk.createEngine(
            CreateEngineParams(
                language = "zh-en",
                mode = RunMode.OFFLINE,
                voiceId = primaryVoiceId,
            ),
        )
        val englishEngine = TextToSpeechSdk.createEngine(
            CreateEngineParams(
                language = "en-US",
                mode = RunMode.OFFLINE,
                voiceId = primaryVoiceId,
            ),
        )

        engines += mixedEngine
        engines += englishEngine
    }

    @Test
    fun engineNameAppearsInDestroyedErrorMessage() {
        val engine = TextToSpeechSdk.createEngine(
            CreateEngineParams(
                language = "zh-en",
                mode = RunMode.OFFLINE,
                voiceId = primaryVoiceId,
                engineName = "xiaoqiao-tts",
            ),
        )
        engines += engine
        val listener = RecordingListener(errorTarget = 1)
        engine.setListener(listener)

        engine.shutdown()
        engine.speak("after shutdown", SpeakParams(requestId = "named-destroyed"))

        assertTrue(listener.awaitErrors())
        assertTrue(listener.errors.single().message.contains("engineName=xiaoqiao-tts"))
    }

    @Test
    fun createEngineRejectsDisabledModelLoadOnCreate() {
        val error = expectTtsException {
            TextToSpeechSdk.createEngine(
                CreateEngineParams(
                    language = "zh-en",
                    mode = RunMode.OFFLINE,
                    voiceId = primaryVoiceId,
                    modelLoadOnCreate = false,
                ),
            )
        }

        assertEquals(TtsErrorCode.CREATE_ENGINE_FAILED, error.errorCode)
    }

    @Test
    fun createEngineCallbackRunsAsynchronously() {
        val callerThread = Thread.currentThread().name
        val callbackThread = AtomicReference<String>()
        val engineResult = AtomicReference<TextToSpeechEngine>()
        val latch = CountDownLatch(1)

        TextToSpeechSdk.createEngine(
            CreateEngineParams(
                language = "zh-en",
                mode = RunMode.OFFLINE,
                voiceId = primaryVoiceId,
            ),
            object : Callback<TextToSpeechEngine> {
                override fun onSuccess(result: TextToSpeechEngine) {
                    callbackThread.set(Thread.currentThread().name)
                    engineResult.set(result)
                    latch.countDown()
                }

                override fun onError(errorCode: Int, errorMessage: String) {
                    throw AssertionError("Unexpected createEngine error: $errorCode $errorMessage")
                }
            },
        )

        assertTrue(latch.await(5, TimeUnit.SECONDS))
        engines += engineResult.get()
        assertNotEquals(callerThread, callbackThread.get())
    }

    @Test
    fun setWorkPathMustRunBeforeCreateEngine() {
        val engine = newEngine("zh-en", primaryVoiceId)

        val error = expectTtsException {
            TextToSpeechSdk.setWorkPath("/tmp/lits-tts")
        }

        assertEquals(TtsErrorCode.INTERNAL_SERVICE_ERROR, error.errorCode)
        engine.shutdown()
    }

    @Test
    fun synthesizeOnlyEmitsDataAndSynthesisComplete() {
        val engine = newEngine("zh-en", primaryVoiceId)
        val listener = RecordingListener(completeTarget = 1)
        engine.setListener(listener)

        engine.speak(
            "hello world",
            SpeakParams(requestId = "req-1", playType = PlayType.SYNTHESIZE_ONLY),
        )

        assertTrue(listener.awaitComplete())
        assertEquals(listOf("start:req-1"), listener.starts)
        assertTrue(listener.dataEvents.isNotEmpty())
        assertEquals(listOf("complete:req-1:SYNTHESIS_COMPLETE"), listener.completes)
        assertFalse(engine.isBusy())
    }

    @Test
    fun synthesizeAndPlayDoesNotEmitDataAndEmitsTwoCompleteEvents() {
        val engine = newEngine("en-US", primaryVoiceId)
        val listener = RecordingListener(completeTarget = 2)
        engine.setListener(listener)

        engine.speak(
            "hello world",
            SpeakParams(requestId = "req-2", playType = PlayType.SYNTHESIZE_AND_PLAY),
        )

        assertTrue(listener.awaitComplete())
        assertTrue(listener.dataEvents.isEmpty())
        assertEquals(
            listOf(
                "complete:req-2:SYNTHESIS_COMPLETE",
                "complete:req-2:PLAYBACK_COMPLETE",
            ),
            listener.completes,
        )
    }

    @Test
    fun speakValidatesTextLengthRangesAudioTypeAndLanguageContext() {
        val engine = newEngine("zh-en", primaryVoiceId)
        val listener = RecordingListener(errorTarget = 5)
        engine.setListener(listener)

        engine.speak(" ", SpeakParams(requestId = "bad-text"))
        engine.speak("ok", SpeakParams(requestId = "speed", speed = 2.1f))
        engine.speak("ok", SpeakParams(requestId = "pitch", pitch = 0.4f))
        engine.speak("ok", SpeakParams(requestId = "audio", audioType = "wav"))
        engine.speak("ok", SpeakParams(requestId = "context-ok", languageContext = "zh-en"))
        engine.speak("ok", SpeakParams(requestId = "context-bad", languageContext = "zh-CN"))

        assertTrue(listener.awaitErrors())
        assertEquals(TtsErrorCode.TEXT_LENGTH_INVALID, listener.errors[0].code)
        assertEquals(TtsErrorCode.RUNTIME_EXCEPTION, listener.errors[1].code)
        assertEquals(TtsErrorCode.RUNTIME_EXCEPTION, listener.errors[2].code)
        assertEquals(TtsErrorCode.RUNTIME_EXCEPTION, listener.errors[3].code)
        assertEquals(TtsErrorCode.RUNTIME_EXCEPTION, listener.errors[4].code)
    }

    @Test
    fun speakValidationErrorsAreDispatchedAsynchronously() {
        val engine = newEngine("zh-en", primaryVoiceId)
        val callerThread = Thread.currentThread().name
        val listener = RecordingListener(errorTarget = 1)
        engine.setListener(listener)

        engine.speak(" ", SpeakParams(requestId = "async-bad-text"))

        assertTrue(listener.awaitErrors())
        assertEquals(TtsErrorCode.TEXT_LENGTH_INVALID, listener.errors.single().code)
        assertNotEquals(callerThread, listener.errors.single().threadName)
    }

    @Test
    fun duplicateRequestErrorsAreDispatchedAsynchronously() {
        val engine = newEngine("zh-en", primaryVoiceId)
        val callerThread = Thread.currentThread().name
        val listener = RecordingListener(errorTarget = 1)
        engine.setListener(listener)

        engine.speak(
            "hello world",
            SpeakParams(requestId = "dup-req", playType = PlayType.SYNTHESIZE_ONLY),
        )
        engine.speak(
            "hello again",
            SpeakParams(requestId = "dup-req", playType = PlayType.SYNTHESIZE_ONLY),
        )

        assertTrue(listener.awaitErrors())
        assertEquals(TtsErrorCode.RUNTIME_EXCEPTION, listener.errors.single().code)
        assertNotEquals(callerThread, listener.errors.single().threadName)
    }

    @Test
    fun preemptStopsPreviousRequestAndRunsNewRequest() {
        val engine = newEngine("zh-en", primaryVoiceId)
        val listener = RecordingListener(completeTarget = 2, stopTarget = 1)
        val callerThread = Thread.currentThread().name
        engine.setListener(listener)

        engine.speak("first request ".repeat(80), SpeakParams(requestId = "old"))
        engine.speak("new request", SpeakParams(requestId = "new", queueMode = QueueMode.PREEMPT))

        assertTrue(listener.awaitStop())
        assertTrue(listener.awaitComplete())
        assertTrue(listener.stops.contains("stop:old:STOP_ALL"))
        assertTrue(listener.stopThreads.all { it != callerThread })
        assertTrue(listener.completes.contains("complete:new:SYNTHESIS_COMPLETE"))
        assertTrue(listener.completes.contains("complete:new:PLAYBACK_COMPLETE"))
    }

    @Test
    fun stopStopsActiveAndQueuedRequests() {
        val engine = newEngine("zh-en", primaryVoiceId)
        val listener = RecordingListener(stopTarget = 2)
        val callerThread = Thread.currentThread().name
        engine.setListener(listener)

        engine.speak("first request ".repeat(80), SpeakParams(requestId = "active"))
        engine.speak("queued request", SpeakParams(requestId = "queued"))
        engine.stop()

        assertTrue(listener.awaitStop())
        assertTrue(listener.stops.contains("stop:active:STOP_ALL"))
        assertTrue(listener.stops.contains("stop:queued:STOP_ALL"))
        assertTrue(listener.stopThreads.all { it != callerThread })
        assertFalse(engine.isBusy())
    }

    @Test
    fun shutdownDestroysEngine() {
        val engine = newEngine("zh-en", primaryVoiceId)
        val listener = RecordingListener(errorTarget = 1)
        engine.setListener(listener)

        engine.shutdown()
        engine.speak("after shutdown", SpeakParams(requestId = "destroyed"))

        assertTrue(listener.awaitErrors())
        assertEquals(TtsErrorCode.ENGINE_DESTROYED, listener.errors.single().code)
    }

    @Test
    fun destroyedEngineRejectsIsBusyAndRepeatedShutdown() {
        val engine = newEngine("zh-en", primaryVoiceId)

        engine.shutdown()

        assertEquals(TtsErrorCode.ENGINE_DESTROYED, expectTtsException { engine.isBusy() }.errorCode)
        assertEquals(TtsErrorCode.ENGINE_DESTROYED, expectTtsException { engine.shutdown() }.errorCode)
    }

    @Test
    fun destroyedEngineWithoutListenerRejectsSpeakAsDestroyed() {
        val engine = newEngine("zh-en", primaryVoiceId)

        engine.shutdown()

        assertEquals(
            TtsErrorCode.ENGINE_DESTROYED,
            expectTtsException { engine.speak("after shutdown", SpeakParams(requestId = "destroyed-no-listener")) }.errorCode,
        )
    }

    private fun newEngine(language: String, voiceId: String): TextToSpeechEngine {
        val engine = TextToSpeechSdk.createEngine(
            CreateEngineParams(language = language, mode = RunMode.OFFLINE, voiceId = voiceId),
        )
        engines += engine
        return engine
    }

    private fun expectTtsException(block: () -> Unit): TextToSpeechException {
        return try {
            block()
            throw AssertionError("Expected TextToSpeechException")
        } catch (error: TextToSpeechException) {
            error
        }
    }

    private class RecordingListener(
        completeTarget: Int = 0,
        errorTarget: Int = 0,
        stopTarget: Int = 0,
    ) : SpeakListener {
        val starts = Collections.synchronizedList(mutableListOf<String>())
        val dataEvents = Collections.synchronizedList(mutableListOf<String>())
        val completes = Collections.synchronizedList(mutableListOf<String>())
        val stops = Collections.synchronizedList(mutableListOf<String>())
        val stopThreads = Collections.synchronizedList(mutableListOf<String>())
        val errors = Collections.synchronizedList(mutableListOf<ErrorEvent>())

        private val completeLatch = CountDownLatch(completeTarget)
        private val errorLatch = CountDownLatch(errorTarget)
        private val stopLatch = CountDownLatch(stopTarget)

        override fun onStart(requestId: String, response: StartResponse) {
            starts += "start:$requestId"
            assertEquals("pcm", response.audioType)
            assertEquals(16000, response.sampleRate)
            assertEquals(16, response.sampleBit)
            assertEquals(1, response.audioChannel)
            assertEquals(0, response.compressRate)
        }

        override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) {
            dataEvents += "data:$requestId:${response.sequence}:${audio.size}"
            assertEquals("pcm", response.audioType)
        }

        override fun onComplete(requestId: String, response: CompleteResponse) {
            completes += "complete:$requestId:${response.type}"
            completeLatch.countDown()
        }

        override fun onStop(requestId: String, response: StopResponse) {
            stops += "stop:$requestId:${response.type}"
            stopThreads += Thread.currentThread().name
            stopLatch.countDown()
        }

        override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
            errors += ErrorEvent(requestId, errorCode, errorMessage, Thread.currentThread().name)
            errorLatch.countDown()
        }

        fun awaitComplete(): Boolean = completeLatch.await(5, TimeUnit.SECONDS)
        fun awaitErrors(): Boolean = errorLatch.await(5, TimeUnit.SECONDS)
        fun awaitStop(): Boolean = stopLatch.await(5, TimeUnit.SECONDS)
    }

    private data class ErrorEvent(
        val requestId: String,
        val code: Int,
        val message: String,
        val threadName: String,
    )
}
