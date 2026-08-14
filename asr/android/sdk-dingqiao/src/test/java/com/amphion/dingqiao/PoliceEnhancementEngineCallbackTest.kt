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
import org.mockito.kotlin.whenever

class PoliceEnhancementEngineCallbackTest {

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
