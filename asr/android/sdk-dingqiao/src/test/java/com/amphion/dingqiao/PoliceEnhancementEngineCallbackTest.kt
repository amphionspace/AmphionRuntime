package com.amphion.dingqiao

import android.content.Context
import com.amphion.asr.AsrCallback
import com.amphion.asr.AsrEngine
import com.amphion.asr.AsrResult
import com.amphion.asr.AsrSession
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.mockito.kotlin.any
import org.mockito.kotlin.mock
import org.mockito.kotlin.verify
import org.mockito.kotlin.whenever

class PoliceEnhancementEngineCallbackTest {

    @Test
    fun finishThenShutdownWaitsForUniqueLastAndComplete() {
        val nativeCallbacks = ConcurrentLinkedQueue<AsrCallback>()
        val session = mock<AsrSession>()
        val asrEngine = mock<AsrEngine>()
        whenever(asrEngine.newSession(any(), any())).thenAnswer { invocation ->
            nativeCallbacks.add(invocation.getArgument(0))
            session
        }
        val callbackExecutor = Executors.newSingleThreadExecutor()
        val callbackEvents = CopyOnWriteArrayList<String>()
        val completed = CountDownLatch(1)
        val shutdownReturned = CountDownLatch(1)
        val workPath = kotlin.io.path.createTempDirectory().toFile()
        val publicEngine = DingqiaoRecognitionEngine(
            appContext = mock<Context>(),
            createParams = CreateEngineParams(language = "zh-CN"),
            voiceprintStore = VoiceprintStore(workPath),
            speakerModelPath = null,
            callbackExecutor = callbackExecutor,
            onShutdown = {},
            preloadedEngine = asrEngine,
            injectedTextEnhancer = { it },
        )
        publicEngine.setListener(object : RecognitionListener {
            override fun onStart(sessionId: String, eventMessage: String) = Unit
            override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) = Unit
            override fun onResult(sessionId: String, result: SpeechRecognitionResult) {
                if (result.isLast) callbackEvents += "last:${result.result}"
            }
            override fun onComplete(sessionId: String, eventMessage: String) {
                callbackEvents += "complete"
                completed.countDown()
            }
            override fun onError(sessionId: String, errorCode: Int, errorMessage: String) = Unit
        })

        try {
            publicEngine.startListening(StartParams(sessionId = "finish-shutdown", audioInfo = AudioInfo()))
            val nativeCallback = nativeCallbacks.remove()
            publicEngine.finish("finish-shutdown")
            verify(session).stop()

            Thread {
                publicEngine.shutdown()
                shutdownReturned.countDown()
            }.start()
            assertFalse("shutdown must wait for terminal callbacks", shutdownReturned.await(100, TimeUnit.MILLISECONDS))

            nativeCallback.onFinal(AsrResult(text = "完成", isLast = true))
            assertTrue(completed.await(5, TimeUnit.SECONDS))
            assertTrue(shutdownReturned.await(5, TimeUnit.SECONDS))
            assertEquals(listOf("last:完成", "complete"), callbackEvents.toList())
            verify(asrEngine).close()
        } finally {
            publicEngine.shutdown()
            callbackExecutor.shutdownNow()
            workPath.deleteRecursively()
        }
    }

    @Test
    fun shutdownFromCompleteCallbackReturnsAndReleasesAfterTerminalCallback() {
        val nativeCallbacks = ConcurrentLinkedQueue<AsrCallback>()
        val session = mock<AsrSession>()
        val asrEngine = mock<AsrEngine>()
        whenever(asrEngine.newSession(any(), any())).thenAnswer { invocation ->
            nativeCallbacks.add(invocation.getArgument(0))
            session
        }
        val callbackExecutor = Executors.newSingleThreadExecutor()
        val callbackEvents = CopyOnWriteArrayList<String>()
        val shutdownComplete = CountDownLatch(1)
        val workPath = kotlin.io.path.createTempDirectory().toFile()
        lateinit var publicEngine: DingqiaoRecognitionEngine
        publicEngine = DingqiaoRecognitionEngine(
            appContext = mock<Context>(),
            createParams = CreateEngineParams(language = "zh-CN"),
            voiceprintStore = VoiceprintStore(workPath),
            speakerModelPath = null,
            callbackExecutor = callbackExecutor,
            onShutdown = {
                callbackEvents += "released"
                shutdownComplete.countDown()
            },
            preloadedEngine = asrEngine,
            injectedTextEnhancer = { it },
        )
        publicEngine.setListener(object : RecognitionListener {
            override fun onStart(sessionId: String, eventMessage: String) = Unit
            override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) = Unit
            override fun onResult(sessionId: String, result: SpeechRecognitionResult) {
                if (result.isLast) callbackEvents += "last"
            }
            override fun onComplete(sessionId: String, eventMessage: String) {
                callbackEvents += "complete-enter"
                publicEngine.shutdown()
                callbackEvents += "complete-return"
            }
            override fun onError(sessionId: String, errorCode: Int, errorMessage: String) = Unit
        })

        try {
            publicEngine.startListening(StartParams("callback-shutdown", AudioInfo()))
            publicEngine.finish("callback-shutdown")
            nativeCallbacks.remove().onFinal(AsrResult(text = "完成", isLast = true))

            assertTrue(shutdownComplete.await(5, TimeUnit.SECONDS))
            assertEquals(
                listOf("last", "complete-enter", "complete-return", "released"),
                callbackEvents.toList(),
            )
            verify(asrEngine).close()
        } finally {
            publicEngine.shutdown()
            callbackExecutor.shutdownNow()
            workPath.deleteRecursively()
        }
    }

    @Test
    fun rejectedPartialPublishesEmptyNonLastFinalAndKeepsSessionActive() {
        val nativeCallbacks = ConcurrentLinkedQueue<AsrCallback>()
        val asrEngine = mock<AsrEngine>()
        whenever(asrEngine.newSession(any(), any())).thenAnswer { invocation ->
            nativeCallbacks.add(invocation.getArgument(0))
            mock<AsrSession>()
        }
        val callbackExecutor = Executors.newSingleThreadExecutor()
        val callbackEvents = CopyOnWriteArrayList<String>()
        val completed = CountDownLatch(1)
        val workPath = kotlin.io.path.createTempDirectory().toFile()
        val publicEngine: SpeechRecognitionEngine = DingqiaoRecognitionEngine(
            appContext = mock<Context>(),
            createParams = CreateEngineParams(language = "zh-CN"),
            voiceprintStore = VoiceprintStore(workPath),
            speakerModelPath = null,
            callbackExecutor = callbackExecutor,
            onShutdown = {},
            preloadedEngine = asrEngine,
            injectedTextEnhancer = { it },
        )
        publicEngine.setListener(object : RecognitionListener {
            override fun onStart(sessionId: String, eventMessage: String) {
                callbackEvents += "$sessionId:start"
            }

            override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) {
                callbackEvents += "$sessionId:event:$eventCode"
            }

            override fun onResult(sessionId: String, result: SpeechRecognitionResult) {
                callbackEvents +=
                    "$sessionId:result:${result.result}:${result.isFinal}:${result.isLast}:${result.speakerSimilarity}"
            }

            override fun onComplete(sessionId: String, eventMessage: String) {
                callbackEvents += "$sessionId:complete"
                completed.countDown()
            }

            override fun onError(sessionId: String, errorCode: Int, errorMessage: String) {
                callbackEvents += "$sessionId:error:$errorCode"
            }
        })

        try {
            publicEngine.startListening(StartParams(sessionId = "rejected", audioInfo = AudioInfo()))
            val nativeCallback = nativeCallbacks.remove()
            nativeCallback.onPartial("非目标说话人")
            nativeCallback.onFinalRejected(AsrResult(text = "", isLast = false, speakerScore = 0.12f))

            val drained = CountDownLatch(1)
            callbackExecutor.execute { drained.countDown() }
            assertTrue(drained.await(5, TimeUnit.SECONDS))

            assertEquals(
                listOf(
                    "rejected:start",
                    "rejected:result:非目标说话人:false:false:null",
                    "rejected:event:${DingqiaoEventCode.SPEAKER_VAD_REJECTED}",
                    "rejected:result::true:false:0.12",
                ),
                callbackEvents.toList(),
            )
            assertTrue(publicEngine.isBusy())

            nativeCallback.onFinalRejected(AsrResult(text = "", isLast = true, speakerScore = 0.08f))
            assertTrue(completed.await(5, TimeUnit.SECONDS))
            assertEquals(
                listOf(
                    "rejected:start",
                    "rejected:result:非目标说话人:false:false:null",
                    "rejected:event:${DingqiaoEventCode.SPEAKER_VAD_REJECTED}",
                    "rejected:result::true:false:0.12",
                    "rejected:event:${DingqiaoEventCode.SPEAKER_VAD_REJECTED}",
                    "rejected:result::true:true:0.08",
                    "rejected:complete",
                ),
                callbackEvents.toList(),
            )
            assertFalse(publicEngine.isBusy())
        } finally {
            publicEngine.shutdown()
            callbackExecutor.shutdownNow()
            workPath.deleteRecursively()
        }
    }

    @Test
    fun queuedPartialIsDeliveredWhenRuntimeSpeakerVadEnableReturns() {
        assertQueuedPartialDelivery(partialRequested = true, expected = listOf("allowed-partial"))
    }

    @Test
    fun queuedPartialStaysSuppressedWhenCallerDisabledPartials() {
        assertQueuedPartialDelivery(partialRequested = false, expected = emptyList())
    }

    private fun assertQueuedPartialDelivery(partialRequested: Boolean, expected: List<String>) {
        val nativeCallbacks = ConcurrentLinkedQueue<AsrCallback>()
        val session = mock<AsrSession>()
        val asrEngine = mock<AsrEngine>()
        whenever(asrEngine.newSession(any(), any())).thenAnswer { invocation ->
            nativeCallbacks.add(invocation.getArgument(0))
            session
        }
        val callbackExecutor = Executors.newSingleThreadExecutor()
        val executorBlocked = CountDownLatch(1)
        val releaseExecutor = CountDownLatch(1)
        callbackExecutor.execute {
            executorBlocked.countDown()
            releaseExecutor.await(5, TimeUnit.SECONDS)
        }
        assertTrue(executorBlocked.await(5, TimeUnit.SECONDS))

        val workPath = kotlin.io.path.createTempDirectory().toFile()
        val store = VoiceprintStore(workPath)
        val voiceprintId = store.saveVoiceprint(listOf("sample.pcm"), floatArrayOf(1f, 0f)).voiceprintId.keys.single()
        val speakerModel = store.speakerModelPath().apply { writeBytes(byteArrayOf(1)) }
        val results = CopyOnWriteArrayList<String>()
        val publicEngine: SpeechRecognitionEngine = DingqiaoRecognitionEngine(
            appContext = mock<Context>(),
            createParams = CreateEngineParams(language = "zh-CN"),
            voiceprintStore = store,
            speakerModelPath = speakerModel.absolutePath,
            callbackExecutor = callbackExecutor,
            onShutdown = {},
            preloadedEngine = asrEngine,
            injectedTextEnhancer = { it },
        )
        publicEngine.setListener(object : RecognitionListener {
            override fun onStart(sessionId: String, eventMessage: String) = Unit
            override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) = Unit
            override fun onResult(sessionId: String, result: SpeechRecognitionResult) {
                results += result.result
            }
            override fun onComplete(sessionId: String, eventMessage: String) = Unit
            override fun onError(sessionId: String, errorCode: Int, errorMessage: String) = Unit
        })

        try {
            publicEngine.startListening(
                StartParams(
                    sessionId = "runtime-speaker-vad",
                    audioInfo = AudioInfo(),
                    extraParams = mapOf(
                        "voiceprintIds" to listOf(voiceprintId),
                        "enablePartialResult" to partialRequested,
                    ),
                ),
            )
            nativeCallbacks.remove().onPartial("allowed-partial")
            publicEngine.setSpeakerVadEnabled(true)

            releaseExecutor.countDown()
            val drained = CountDownLatch(1)
            callbackExecutor.execute { drained.countDown() }
            assertTrue(drained.await(5, TimeUnit.SECONDS))
            assertEquals(expected, results)
        } finally {
            releaseExecutor.countDown()
            publicEngine.shutdown()
            callbackExecutor.shutdownNow()
            workPath.deleteRecursively()
        }
    }

    @Test
    fun publicEngineSnapshotsTogglePerSessionAndPreservesTerminalCallbackContract() {
        val nativeCallbacks = ConcurrentLinkedQueue<AsrCallback>()
        val asrEngine = mock<AsrEngine>()
        whenever(asrEngine.newSession(any(), any())).thenAnswer { invocation ->
            nativeCallbacks.add(invocation.getArgument(0))
            mock<AsrSession>()
        }
        val callbackExecutor = Executors.newSingleThreadExecutor()
        val callbackEvents = CopyOnWriteArrayList<String>()
        val firstComplete = CountDownLatch(1)
        val allComplete = CountDownLatch(2)
        var enhancerCalls = 0
        val publicEngine: SpeechRecognitionEngine = DingqiaoRecognitionEngine(
            appContext = mock<Context>(),
            createParams = CreateEngineParams(language = "zh-CN"),
            voiceprintStore = VoiceprintStore(kotlin.io.path.createTempDirectory().toFile()),
            speakerModelPath = null,
            callbackExecutor = callbackExecutor,
            onShutdown = {},
            preloadedEngine = asrEngine,
            injectedTextEnhancer = { raw ->
                enhancerCalls += 1
                "$raw-增强"
            },
        )
        publicEngine.setListener(object : RecognitionListener {
            override fun onStart(sessionId: String, eventMessage: String) {
                callbackEvents += "$sessionId:start"
            }

            override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) = Unit

            override fun onResult(sessionId: String, result: SpeechRecognitionResult) {
                callbackEvents += "$sessionId:result:${result.result}:${result.isFinal}:${result.isLast}"
            }

            override fun onComplete(sessionId: String, eventMessage: String) {
                callbackEvents += "$sessionId:complete"
                if (sessionId == "off") firstComplete.countDown()
                allComplete.countDown()
            }

            override fun onError(sessionId: String, errorCode: Int, errorMessage: String) {
                callbackEvents += "$sessionId:error:$errorCode"
            }
        })

        try {
            publicEngine.startListening(
                StartParams(
                    sessionId = "off",
                    audioInfo = AudioInfo(),
                    extraParams = mapOf("enablePoliceEnhancement" to false),
                ),
            )
            nativeCallbacks.remove().onFinal(AsrResult(text = "第一句", isLast = true))
            assertTrue(firstComplete.await(5, TimeUnit.SECONDS))
            assertFalse(publicEngine.isBusy())

            publicEngine.startListening(
                StartParams(
                    sessionId = "on",
                    audioInfo = AudioInfo(),
                    extraParams = mapOf("enablePoliceEnhancement" to true),
                ),
            )
            nativeCallbacks.remove().onFinal(AsrResult(text = "第二句", isLast = true))
            assertTrue(allComplete.await(5, TimeUnit.SECONDS))
            assertFalse(publicEngine.isBusy())

            assertEquals(
                listOf(
                    "off:start",
                    "off:result:第一句:true:true",
                    "off:complete",
                    "on:start",
                    "on:result:第二句-增强:true:true",
                    "on:complete",
                ),
                callbackEvents.toList(),
            )
            assertEquals(1, enhancerCalls)
        } finally {
            publicEngine.shutdown()
            callbackExecutor.shutdownNow()
        }
    }
}
