package com.amphion.dingqiao.demo

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.AudioInfo
import com.amphion.dingqiao.CreateEngineParams
import com.amphion.dingqiao.DingqiaoOnlineMode
import com.amphion.dingqiao.SpeechRecognitionEngine
import com.amphion.dingqiao.SpeechRecognizeSdk
import com.amphion.dingqiao.StartParams
import java.io.File
import java.io.FileInputStream
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class DingqiaoNativeEndpointParityInstrumentedTest {

    private val targetContext: Context
        get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val testContext: Context
        get() = InstrumentationRegistry.getInstrumentation().context

    @Test
    fun nativeRule3TransitionsPreserveContinuousSession() {
        prepareSdkRuntime(
            targetContext,
            File(targetContext.getExternalFilesDir(null), "dingqiao_work_endpoint_parity"),
        )
        val engine = SpeechRecognizeSdk.createEngine(
            CreateEngineParams(
                language = "zh-CN",
                online = DingqiaoOnlineMode.OFFLINE,
            ),
        )
        try {
            val wav = mainWavs(testContext).maxByOrNull { readAssetPcm(testContext, it).size }
                ?: error("no test wav; pass -PdingqiaoEvalAudioDir=/path/to/wav")
            val pcm = readAssetPcm(testContext, wav)

            assertEmptyRule3RecoversWithSpeech(engine, pcm)
            assertRepeatedRule3DoesNotEndSession(engine, pcm)
            assertEndpointRuleChangeRebuildsUsableEngine(engine, pcm)
            assertLongModeDoesNotUsePeriodicRule3(engine, pcm)
        } finally {
            engine.shutdown()
        }
    }

    private fun assertEmptyRule3RecoversWithSpeech(engine: SpeechRecognitionEngine, pcm: ByteArray) {
        val listener = CapturingListener().also { engine.setListener(it) }
        val sessionId = "empty-rule3-${System.currentTimeMillis()}"
        val transitionBaseline = transitionLines().size
        engine.startListening(startParams(sessionId, endpointMaxUtteranceMs = 1_000))
        assertTrue("empty Rule3 session failed to start: ${listener.errors}", listener.awaitStarted(15_000))

        // The transducer has bounded right-context latency, so feed enough decoded silence for
        // native Rule3's 1s utterance threshold to become observable without ASR evidence.
        feedSilence(engine, sessionId, 8_000)
        val emptyRule3Observed = awaitTransitionCount(
            transitionBaseline,
            1,
            "hard-restart",
            "native-rule3",
            false,
        )
        assertTrue(
            "empty Rule3 transition was not observed; AmphionMetrics=${transitionLog()}",
            emptyRule3Observed,
        )
        assertSingleTransitionSession(
            transitionsSince(transitionBaseline, "hard-restart", "native-rule3", false),
            "empty Rule3",
        )
        assertTrue("empty Rule3 produced an error: ${listener.errors}", listener.errors.isEmpty())
        assertFalse("empty Rule3 must not complete the session", listener.completes.isNotEmpty())
        assertEquals("empty Rule3 must not emit isLast", 0, listener.finals.count { it.isLast })

        feedFrames(engine, sessionId, pcm.copyOfRange(0, minOf(pcm.size, DQ_SR * 2 * 5)), DQ_FRAME_MS)
        engine.finish(sessionId)
        assertTrue("finish after empty Rule3 timed out: ${listener.errors}", listener.awaitComplete(30_000))

        assertTrue("speech after empty Rule3 must produce a non-empty final", listener.finalText().isNotBlank())
        assertNormalCompletion(listener, sessionId, "empty Rule3")
    }

    private fun assertRepeatedRule3DoesNotEndSession(engine: SpeechRecognitionEngine, pcm: ByteArray) {
        val listener = CapturingListener().also { engine.setListener(it) }
        val sessionId = "checkpoint-${System.currentTimeMillis()}"
        val transitionBaseline = transitionLines().size
        engine.startListening(startParams(sessionId, endpointMaxUtteranceMs = 1_000))
        assertTrue("checkpoint session failed to start: ${listener.errors}", listener.awaitStarted(15_000))

        feedFrames(engine, sessionId, pcm.copyOfRange(0, minOf(pcm.size, DQ_SR * 2 * 7)), DQ_FRAME_MS)
        assertTrue(
            "expected at least two observed native Rule3 checkpoints",
            awaitTransitionCount(
                transitionBaseline,
                2,
                "native-checkpoint",
                "native-rule3",
                true,
            ),
        )
        val checkpoints = transitionsSince(
            transitionBaseline,
            "native-checkpoint",
            "native-rule3",
            true,
        )
        assertSingleTransitionSession(checkpoints, "Rule3 checkpoints")
        val nonEmptyFinalsBeforeFinish = listener.finals.count { it.result.isNotBlank() }
        assertTrue("expected repeated non-empty Rule3 finals, got $nonEmptyFinalsBeforeFinish",
            nonEmptyFinalsBeforeFinish >= 2)
        assertEquals("Rule3 checkpoints must not emit isLast before finish", 0,
            listener.finals.count { it.isLast })
        assertFalse("Rule3 checkpoints must not complete the session", listener.awaitComplete(0))

        engine.finish(sessionId)
        assertTrue("checkpoint session finish timed out: ${listener.errors}", listener.awaitComplete(30_000))
        assertNormalCompletion(listener, sessionId, "checkpoint session")
    }

    private fun assertEndpointRuleChangeRebuildsUsableEngine(
        engine: SpeechRecognitionEngine,
        pcm: ByteArray,
    ) {
        val listener = CapturingListener().also { engine.setListener(it) }
        val sessionId = "reconfigure-rule3-${System.currentTimeMillis()}"
        val transitionBaseline = transitionLines().size
        engine.startListening(startParams(sessionId, endpointMaxUtteranceMs = 5_000))
        assertTrue("reconfigured engine failed to start: ${listener.errors}", listener.awaitStarted(20_000))

        feedFrames(engine, sessionId, pcm.copyOfRange(0, minOf(pcm.size, DQ_SR * 2 * 2)), DQ_FRAME_MS)
        assertFalse("reconfigured session must remain active before finish", listener.awaitComplete(0))
        assertEquals("reconfigured session must not emit isLast before finish", 0,
            listener.finals.count { it.isLast })
        engine.finish(sessionId)
        assertTrue("reconfigured engine finish timed out: ${listener.errors}", listener.awaitComplete(30_000))
        assertTrue(
            "5s endpoint rule must not reuse the previous 1s Rule3 configuration: ${transitionLog()}",
            transitionsSince(transitionBaseline, reason = "native-rule3").isEmpty(),
        )
        assertTrue("reconfigured engine must produce non-empty text", listener.finalText().isNotBlank())
        assertNormalCompletion(listener, sessionId, "reconfigured session")
    }

    private fun assertLongModeDoesNotUsePeriodicRule3(
        engine: SpeechRecognitionEngine,
        pcm: ByteArray,
    ) {
        val listener = CapturingListener().also { engine.setListener(it) }
        val sessionId = "long-no-rule3-${System.currentTimeMillis()}"
        val transitionBaseline = transitionLines().size
        engine.startListening(
            startParams(
                sessionId = sessionId,
                endpointMaxUtteranceMs = 1_000,
                recognizerMode = "long",
            ),
        )
        assertTrue("long session failed to start: ${listener.errors}", listener.awaitStarted(20_000))

        feedFrames(engine, sessionId, pcm.copyOfRange(0, minOf(pcm.size, DQ_SR * 2 * 7)), DQ_FRAME_MS)
        assertTrue(
            "long mode must ignore endpointMaxUtteranceMs Rule3: ${transitionLog()}",
            transitionsSince(transitionBaseline, reason = "native-rule3").isEmpty(),
        )
        assertEquals("long mode must not emit isLast before finish", 0, listener.finals.count { it.isLast })
        assertFalse("long mode must remain active before finish", listener.awaitComplete(0))

        engine.finish(sessionId)
        assertTrue("long session finish timed out: ${listener.errors}", listener.awaitComplete(30_000))
        assertTrue("long session must produce non-empty text", listener.finalText().isNotBlank())
        assertNormalCompletion(listener, sessionId, "long session")
    }

    private fun assertNormalCompletion(
        listener: CapturingListener,
        sessionId: String,
        label: String,
    ) {
        assertEquals("$label must emit one last", 1, listener.finals.count { it.isLast })
        assertEquals("$label must complete once", 1, listener.completes.size)
        assertTrue("unexpected $label errors: ${listener.errors}", listener.errors.isEmpty())
        assertTrue(
            "$label callbacks must belong to $sessionId: ${listener.callbackTrace}",
            listener.callbackTrace.all { it.sessionId == sessionId },
        )
        val lastIndex = listener.callbackTrace.indexOfFirst {
            it.kind == CapturedCallbackKind.FINAL && it.isLast
        }
        val completeIndex = listener.callbackTrace.indexOfFirst {
            it.kind == CapturedCallbackKind.COMPLETE
        }
        assertTrue("$label last must precede complete", lastIndex >= 0 && completeIndex > lastIndex)
    }

    private fun awaitTransitionCount(
        baseline: Int,
        expected: Int,
        action: String? = null,
        reason: String? = null,
        evidence: Boolean? = null,
    ): Boolean {
        val deadline = System.currentTimeMillis() + 5_000
        while (System.currentTimeMillis() < deadline) {
            if (transitionsSince(baseline, action, reason, evidence).size >= expected) return true
            Thread.sleep(50)
        }
        return transitionsSince(baseline, action, reason, evidence).size >= expected
    }

    private fun transitionsSince(
        baseline: Int,
        action: String? = null,
        reason: String? = null,
        evidence: Boolean? = null,
    ): List<String> = transitionLines().drop(baseline).filter { line ->
        (action == null || line.contains("action=$action")) &&
            (reason == null || line.contains("reason=$reason")) &&
            (evidence == null || line.contains("evidence=$evidence"))
    }

    private fun transitionLines(): List<String> {
        val command =
            "logcat --pid=${android.os.Process.myPid()} -d -v brief -s AmphionMetrics:I"
        val descriptor = InstrumentationRegistry.getInstrumentation().uiAutomation
            .executeShellCommand(command)
        val output = descriptor.use {
            FileInputStream(it.fileDescriptor).bufferedReader().use { reader -> reader.readText() }
        }
        return output.lineSequence().filter { it.contains("kind=STREAM_TRANSITION") }.toList()
    }

    private fun assertSingleTransitionSession(lines: List<String>, label: String) {
        val sessionIds = lines.mapNotNull { line ->
            Regex("sessionId=([0-9]+)").find(line)?.groupValues?.get(1)
        }.toSet()
        assertEquals("$label must belong to one native session: $lines", 1, sessionIds.size)
    }

    private fun transitionLog(): String = transitionLines().joinToString(" | ")

    private fun startParams(
        sessionId: String,
        endpointMaxUtteranceMs: Int,
        recognizerMode: String = "short",
    ): StartParams =
        StartParams(
            sessionId = sessionId,
            audioInfo = AudioInfo(),
            extraParams = mapOf(
                "endpointMaxUtteranceMs" to endpointMaxUtteranceMs,
                "recognizerMode" to recognizerMode,
                "enableContinuousRecognition" to true,
                "enablePartialResult" to true,
                "enablePoliceEnhancement" to false,
                "vadEnd" to 10_000,
            ),
        )
}
