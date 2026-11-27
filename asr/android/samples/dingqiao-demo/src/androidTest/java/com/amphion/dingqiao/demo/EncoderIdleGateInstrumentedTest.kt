package com.amphion.dingqiao.demo

import android.os.Handler
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.asr.AmphionRuntime
import com.amphion.asr.AsrCallback
import com.amphion.asr.AsrConfig
import com.amphion.asr.AsrEngine
import com.amphion.asr.AsrError
import com.amphion.asr.AsrLanguage
import com.amphion.asr.AsrResult
import com.amphion.asr.AsrSession
import com.amphion.asr.EndpointRules
import com.amphion.asr.VadConfig
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/** Public PCM/callback regressions, with decoder-thread state snapshots for boundary attribution. */
@RunWith(AndroidJUnit4::class)
class EncoderIdleGateInstrumentedTest {
    private val ctx get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val testCtx get() = InstrumentationRegistry.getInstrumentation().context
    private val report by lazy {
        File(ctx.filesDir, "encoder_idle_regression/${System.currentTimeMillis()}/report.jsonl")
            .also { it.parentFile!!.mkdirs() }
    }

    @Before
    fun prepare() {
        prepareSdkRuntime(ctx, File(ctx.filesDir, "encoder_idle_runtime"))
    }

    @Test
    fun continuousCheckpointKeepsEncoderActive() {
        val config = config().endpointRules(EndpointRules(
            rule1MinTrailingSilenceSec = 100f,
            rule2MinTrailingSilenceSec = 100f,
            rule3MinUtteranceLengthSec = 2f,
        )).vadConfig(VadConfig(activeEndpointSilenceMs = 0)).build()
        AmphionRuntime.create(ctx, AsrLanguage.ZH_EN, config).use { engine ->
            val capture = Capture()
            engine.newSession(capture).use { session ->
                val pcm = speech()
                feed(session, pcm, 320)
                val state = snapshot(session)
                session.stop()
                capture.awaitStopped()
                record("checkpoint", state + capture.summary() + mapOf(
                    "pcmSha256" to digest(pcm),
                    "textSha256" to digest(capture.text().toByteArray()),
                ))
                capture.assertTerminal()
                assertTrue("fixture must exercise a nonempty Rule3 checkpoint",
                    capture.finals.any { !it.isLast && it.text.isNotEmpty() })
                assertEquals("Rule3 retains native audio context; it must not enter IDLE", 0L,
                    state.getValue("idleEntries"))
            }
        }
    }

    @Test
    fun silenceReplayPreservesTextAcrossCallerChunks() {
        val pcm = ShortArray(67_200) + speech() + ShortArray(48_000)
        AmphionRuntime.create(ctx, AsrLanguage.ZH_EN,
            config().vadConfig(VadConfig(activeEndpointSilenceMs = 800)).build()).use { engine ->
            val callerChunk = InstrumentationRegistry.getArguments().getString("encoderIdleCallerChunk")
            val chunks = if (callerChunk == null) listOf(320, 16_000) else {
                require(callerChunk == "320" || callerChunk == "16000") {
                    "encoderIdleCallerChunk must be 320 or 16000"
                }
                listOf(callerChunk.toInt())
            }
            for (chunk in chunks) {
                val control = decode(engine, pcm, chunk, gateEnabled = false)
                val gated = decode(engine, pcm, chunk, gateEnabled = true)
                assertTrue("control fixture must produce text", control.text().isNotEmpty())
                assertEquals("gating changed text for chunk=$chunk", control.text(), gated.text())
                val times = gated.finals.flatMap { it.timestamps }
                assertTrue("token time precedes the real speech onset: $times",
                    times.all { it.isFinite() && it >= 4.0f && it <= pcm.size / 16000f + 1.28f })
            }
        }
    }

    /** The existing project reference is bound to the complete fixture; it is not a control decode. */
    @Test
    fun silenceReplayMatchesFrozenReferenceAcrossCallerChunks() {
        val utterance = speech()
        assertEquals("reference fixture PCM identity",
            "415e13be0e17371a40f89175cdf2b16f38a9f3a6397825bf352a6f221194f29e", digest(utterance))
        // Full REFERENCE in asr/tools/evaluate_automatic_agc_regression.py; human provenance unverified.
        val referenceSha256 = "0f4140253f6e17cc5dbc365266a3af1e56ecfb077f035348bef3465b6cef3824"
        val pcm = ShortArray(67_200) + utterance + ShortArray(48_000)
        var previousTimes: List<Float>? = null
        var previousFinalHashes: List<String>? = null
        AmphionRuntime.create(ctx, AsrLanguage.ZH_EN,
            config().vadConfig(VadConfig(activeEndpointSilenceMs = 800)).build()).use { engine ->
            for (chunk in listOf(320, 16_000)) {
                val gated = decode(engine, pcm, chunk, gateEnabled = true,
                    reportCase = "frozen_reference_replay", comparisonOrder = "gate_only_320_then_16000")
                val actualSha256 = digest(gated.text().toByteArray())
                val times = gated.finals.flatMap { it.timestamps }
                val finalHashes = gated.finals.map { digest(it.text.toByteArray()) }
                record("frozen_reference_check", mapOf("chunkSamples" to chunk,
                    "referenceSha256" to referenceSha256, "referenceCharacters" to 26,
                    "matchesReference" to (actualSha256 == referenceSha256),
                    "finalTextHashes" to finalHashes))
                assertEquals("whole fixture differs from the frozen project reference", referenceSha256, actualSha256)
                assertEquals("reference character count", 26, gated.text().length)
                assertEquals("reference token timestamp count", 26, times.size)
                assertTrue("timestamps must be ordered and within the public PCM clock",
                    times.all { it.isFinite() && it >= 4.0f && it <= pcm.size / 16000f + 1.28f } &&
                        times.zipWithNext().all { (a, b) -> a <= b })
                previousTimes?.let { assertEquals("caller partition changed token times", it, times) }
                previousFinalHashes?.let { assertEquals("caller partition changed final text boundaries", it, finalHashes) }
                previousTimes = times
                previousFinalHashes = finalHashes
            }
        }
    }

    @Test
    fun finishWhileIdlePublishesOneTerminalResult() {
        AmphionRuntime.create(ctx, AsrLanguage.ZH_EN, config().build()).use { engine ->
            val capture = Capture()
            engine.newSession(capture).use { session ->
                feed(session, ShortArray(160_000), 320)
                val state = snapshot(session)
                assertEquals("fixture must reach IDLE", 1L, state.getValue("idle"))
                session.stop()
                capture.awaitStopped()
                record("finish_idle", state + capture.summary())
                capture.assertTerminal()
                assertTrue("silence must not invent speech", capture.text().isEmpty())
            }
        }
    }

    @Test
    fun hotwordsReplacementDoesNotInheritIdleAudio() {
        AmphionRuntime.create(ctx, AsrLanguage.ZH_EN,
            config().hotwords(listOf("初始"), 1.5f).build()).use { engine ->
            val capture = Capture()
            engine.newSession(capture).use { session ->
                feed(session, ShortArray(160_000), 320)
                assertEquals(1L, snapshot(session).getValue("idle"))
                session.updateHotwords(listOf("测试"), 1.5f)
                val state = snapshot(session)
                record("hotwords_replacement", state)
                assertEquals("new stream inherited the old stream's IDLE buffer", 0L,
                    state.getValue("idle"))
                assertEquals(0L, state.getValue("bufferedSamples"))
                session.stop()
                capture.awaitStopped()
                record("hotwords_replacement_terminal", state + capture.summary())
                capture.assertTerminal()
            }
        }
    }

    /** Explicitly selected diagnostic; input is private raw 16 kHz mono PCM16, without padding. */
    @Test
    fun historicalReplayKeepsRecognition() {
        val replayPath = InstrumentationRegistry.getArguments().getString("encoderIdleReplayPath")
        assumeTrue("encoderIdleReplayPath is required for historical replay", !replayPath.isNullOrBlank())
        val bytes = File(requireNotNull(replayPath)).readBytes()
        require(bytes.isNotEmpty() && bytes.size % 2 == 0) { "expected nonempty raw PCM16 input" }
        val shorts = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
        val pcm = ShortArray(shorts.remaining()).also { shorts.get(it) }
        val config = config().endpointRules(EndpointRules(rule3MinUtteranceLengthSec = -1f))
            .vadConfig(VadConfig(activeEndpointSilenceMs = 800)).build()
        AmphionRuntime.create(ctx, AsrLanguage.ZH_EN, config).use { engine ->
            // One engine and one exact PCM buffer; control runs first, then gate.
            val control = decode(engine, pcm, 320, gateEnabled = false, reportCase = "historical_replay")
            val gated = decode(engine, pcm, 320, gateEnabled = true, reportCase = "historical_replay")
            record("historical_text_difference", sanitizedTextDifference(control.text(), gated.text()))
            assertTrue("historical control fixture must produce text", control.text().isNotEmpty())
            // Compare the exact text without exposing customer text through a JUnit failure message.
            assertEquals("historical gate/control text differs; inspect sanitized hashes", true,
                control.text() == gated.text())
        }
    }

    private fun sanitizedTextDifference(controlText: String, gateText: String): Map<String, Any> {
        fun normalized(text: String): IntArray = text.codePoints()
            .filter { Character.isLetterOrDigit(it) }.toArray()
        val control = normalized(controlText)
        val gate = normalized(gateText)
        val lcs = Array(control.size + 1) { IntArray(gate.size + 1) }
        for (i in control.lastIndex downTo 0) {
            for (j in gate.lastIndex downTo 0) {
                lcs[i][j] = if (control[i] == gate[j]) 1 + lcs[i + 1][j + 1]
                    else maxOf(lcs[i + 1][j], lcs[i][j + 1])
            }
        }
        val controlMatched = BooleanArray(control.size)
        val gateMatched = BooleanArray(gate.size)
        var i = 0
        var j = 0
        while (i < control.size && j < gate.size) {
            if (control[i] == gate[j]) {
                controlMatched[i++] = true
                gateMatched[j++] = true
            } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
                i++ // Equal-length alternatives deterministically advance control first.
            } else {
                j++
            }
        }
        fun unmatchedRanges(matched: BooleanArray): List<List<Int>> {
            val ranges = mutableListOf<List<Int>>()
            var index = 0
            while (index < matched.size) {
                if (matched[index]) {
                    index++
                    continue
                }
                val start = index
                while (index < matched.size && !matched[index]) index++
                ranges.add(listOf(start, index))
            }
            return ranges
        }
        val controlRanges = unmatchedRanges(controlMatched)
        val gateRanges = unmatchedRanges(gateMatched)
        return mapOf(
            "algorithm" to "LCS; ties advance control; zero-based half-open intervals",
            "normalization" to "Unicode letter/digit code points; no case folding",
            "controlCharacters" to control.size, "gateCharacters" to gate.size,
            "equal" to control.contentEquals(gate), "rawEqual" to (controlText == gateText),
            "matchedCharacters" to lcs[0][0],
            "controlUnmatched" to (control.size - lcs[0][0]),
            "gateUnmatched" to (gate.size - lcs[0][0]),
            "controlMaxUnmatchedRun" to (controlRanges.maxOfOrNull { it[1] - it[0] } ?: 0),
            "gateMaxUnmatchedRun" to (gateRanges.maxOfOrNull { it[1] - it[0] } ?: 0),
            "controlUnmatchedRanges" to controlRanges, "gateUnmatchedRanges" to gateRanges,
        )
    }

    private fun config() = AsrConfig.Builder().numThreads(diagnosticNumThreads()).punctuation(false).itn(false)

    private fun diagnosticNumThreads(): Int {
        val value = InstrumentationRegistry.getArguments().getString("encoderIdleNumThreads") ?: "2"
        require(value == "1" || value == "2") { "encoderIdleNumThreads must be 1 or 2" }
        return value.toInt()
    }

    private fun speech(): ShortArray {
        val bytes = readAssetPcm(testCtx, "001_recognize.wav")
        val shorts = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
        return ShortArray(shorts.remaining()).also { shorts.get(it) }
    }

    private fun decode(
        engine: AsrEngine,
        pcm: ShortArray,
        chunk: Int,
        gateEnabled: Boolean,
        reportCase: String = "replay",
        comparisonOrder: String = "control_then_gate",
    ): Capture {
        val capture = Capture()
        engine.newSession(capture).use { session ->
            if (!gateEnabled) onDecoder(session) { impl ->
                impl.javaClass.getDeclaredField("encoderIdleGate").apply { isAccessible = true }
                    .set(impl, null)
            }
            val cpuStartedMs = android.os.Process.getElapsedCpuTime()
            val elapsedStartedMs = android.os.SystemClock.elapsedRealtime()
            feed(session, pcm, chunk)
            val state = snapshot(session)
            session.stop()
            capture.awaitStopped()
            val processCpuMs = android.os.Process.getElapsedCpuTime() - cpuStartedMs
            val elapsedMs = android.os.SystemClock.elapsedRealtime() - elapsedStartedMs
            record(reportCase, state + capture.summary() + mapOf("gateEnabled" to gateEnabled, "chunkSamples" to chunk,
                "comparisonOrder" to comparisonOrder, "numThreads" to diagnosticNumThreads(),
                "processCpuMs" to processCpuMs, "elapsedMs" to elapsedMs,
                "pcmSamples" to pcm.size, "pcmSha256" to digest(pcm),
                "textLength" to capture.text().length,
                "textSha256" to digest(capture.text().toByteArray()),
                "timestamps" to capture.finals.flatMap { it.timestamps }.toString()))
            capture.assertTerminal()
            if (gateEnabled) assertTrue("fixture must exercise at least one second of IDLE input",
                state.getValue("idleSamples") >= 16_000)
        }
        return capture
    }

    private fun feed(session: AsrSession, pcm: ShortArray, chunk: Int) {
        var offset = 0
        while (offset < pcm.size) {
            val end = minOf(offset + chunk, pcm.size)
            session.acceptPcmShort(pcm.copyOfRange(offset, end))
            offset = end
        }
    }

    private fun snapshot(session: AsrSession): Map<String, Long> {
        var result = emptyMap<String, Long>()
        onDecoder(session) { impl ->
            fun field(name: String) = impl.javaClass.getDeclaredField(name)
                .apply { isAccessible = true }.get(impl)
            val gate = field("encoderIdleGate")
            fun gateValue(name: String): Long {
                if (gate == null) return 0L
                val value = gate.javaClass.getMethod("get$name").invoke(gate)
                return if (value is Boolean) if (value) 1L else 0L else (value as Number).toLong()
            }
            result = mapOf("publicSamples" to (field("publicSamplesFed") as Long),
                "streamStartSample" to (field("streamStartSample") as Long),
                "idle" to gateValue("Idle"), "idleEntries" to gateValue("IdleEntries"),
                "idleSamples" to gateValue("IdleSamples"), "resumes" to gateValue("Resumes"),
                "bufferedSamples" to gateValue("BufferedSamples"))
        }
        return result
    }

    /** A queue barrier observes all prior public writes without relying on arbitrary sleeps. */
    private fun onDecoder(session: AsrSession, action: (Any) -> Unit) {
        val impl = session.javaClass.getDeclaredField("impl").apply { isAccessible = true }.get(session)!!
        val handler = impl.javaClass.getDeclaredField("decoderHandler").apply { isAccessible = true }
            .get(impl) as Handler
        val done = CountDownLatch(1)
        var failure: Throwable? = null
        check(handler.post {
            try { action(impl) } catch (t: Throwable) { failure = t } finally { done.countDown() }
        })
        assertTrue("decoder did not drain public PCM", done.await(45, TimeUnit.SECONDS))
        failure?.let { throw it }
    }

    private fun record(case: String, values: Map<String, Any>) {
        report.appendText(JSONObject(values + mapOf("case" to case)).toString() + "\n")
    }

    private fun digest(pcm: ShortArray): String = digest(ByteBuffer.allocate(pcm.size * 2)
        .order(ByteOrder.LITTLE_ENDIAN).apply { asShortBuffer().put(pcm) }.array())

    private fun digest(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes)
        .joinToString("") { "%02x".format(it) }

    private class Capture : AsrCallback {
        val finals = Collections.synchronizedList(mutableListOf<AsrResult>())
        private val errors = Collections.synchronizedList(mutableListOf<AsrError>())
        private val events = Collections.synchronizedList(mutableListOf<String>())
        private val stopped = CountDownLatch(1)
        override fun onFinal(result: AsrResult) {
            finals.add(result)
            events.add(if (result.isLast) "last" else "final")
        }
        override fun onError(error: AsrError) { errors.add(error); events.add("error"); stopped.countDown() }
        override fun onSessionStopped() { events.add("stopped"); stopped.countDown() }
        fun awaitStopped() = assertTrue("session did not stop", stopped.await(45, TimeUnit.SECONDS))
        fun text(): String = synchronized(finals) { finals.joinToString("") { it.text } }
        fun summary(): Map<String, Any> {
            val results = synchronized(finals) { finals.toList() }
            val trace = synchronized(events) { events.toList() }
            return mapOf(
                "finals" to results.size,
                "lasts" to results.count { it.isLast },
                "stopped" to trace.count { it == "stopped" },
                "errors" to errors.size,
                "callbackTrace" to trace,
            )
        }
        fun assertTerminal() {
            assertTrue("ASR errors: $errors", errors.isEmpty())
            assertEquals("exactly one last final", 1, finals.count { it.isLast })
            assertEquals("exactly one stopped callback", 1, events.count { it == "stopped" })
            assertEquals(listOf("last", "stopped"), events.takeLast(2))
        }
    }
}
