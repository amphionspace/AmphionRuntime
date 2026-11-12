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
import com.amphion.asr.VadConfig
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Gate-disabled baseline regressions. Reflection only observes the existing decoder-thread state,
 * so these tests also run against the frozen pre-fix main APK without a new native build.
 * Reports and assertion messages contain boundaries/counts/hashes, never recognition text.
 */
@RunWith(AndroidJUnit4::class)
class EncoderIngressPartitionInstrumentedTest {
    private val ctx get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val testCtx get() = InstrumentationRegistry.getInstrumentation().context
    private val report by lazy {
        File(ctx.filesDir, "encoder_ingress_partition/${System.currentTimeMillis()}/report.jsonl")
            .also { it.parentFile!!.mkdirs() }
    }

    @Before
    fun prepare() {
        prepareSdkRuntime(ctx, File(ctx.filesDir, "encoder_idle_runtime"))
    }

    @Test
    fun silenceStreamOriginIsIndependentOfCallerChunks() {
        val pcm = ShortArray(48_000)
        AmphionRuntime.create(ctx, AsrLanguage.ZH_EN, config()).use { engine ->
            val fine = decode(engine, pcm, 320, "silence")
            val coarse = decode(engine, pcm, 16_000, "silence")
            assertTrue("silence must not produce recognition", fine.text.isEmpty() && coarse.text.isEmpty())
            assertEquals("all input must be counted", pcm.size.toLong(), fine.beforeStop.publicSamples)
            assertEquals("all input must be counted", pcm.size.toLong(), coarse.beforeStop.publicSamples)
            assertTrue("fixture must reach a native stream transition", fine.beforeStop.generation > 0)
            assertEquals(
                "caller partition must not change the number of stream transitions",
                fine.beforeStop.generation,
                coarse.beforeStop.generation,
            )
            assertEquals(
                "caller partition must not move the native stream origin",
                fine.beforeStop.streamStartSample,
                coarse.beforeStop.streamStartSample,
            )
        }
    }

    @Test
    fun paddedSpeechTextIsIndependentOfCallerChunks() {
        val bytes = readAssetPcm(testCtx, "001_recognize.wav")
        val samples = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
        val speech = ShortArray(samples.remaining()).also { samples.get(it) }
        val pcm = ShortArray(67_200) + speech + ShortArray(48_000)
        AmphionRuntime.create(ctx, AsrLanguage.ZH_EN, config()).use { engine ->
            val fine = decode(engine, pcm, 320, "padded_speech")
            val coarse = decode(engine, pcm, 16_000, "padded_speech")
            assertEquals("all input must be counted", pcm.size.toLong(), fine.beforeStop.publicSamples)
            assertEquals("all input must be counted", pcm.size.toLong(), coarse.beforeStop.publicSamples)
            assertTrue("speech fixture must produce recognition", fine.text.isNotEmpty() && coarse.text.isNotEmpty())
            // Do not pass either string to assertEquals: JUnit would expose the transcript on failure.
            assertTrue(
                "caller partition changed final text; inspect sanitized length/hash reports",
                fine.text == coarse.text,
            )
            assertEquals(
                "caller partition must preserve public token timestamps",
                fine.timestamps,
                coarse.timestamps,
            )
        }
    }

    private fun config() = AsrConfig.Builder()
        .numThreads(2)
        .punctuation(false)
        .itn(false)
        .vadConfig(VadConfig(activeEndpointSilenceMs = 800))
        .build()

    private fun decode(engine: AsrEngine, pcm: ShortArray, chunk: Int, case: String): Run {
        val capture = Capture()
        return engine.newSession(capture).use { session ->
            onDecoder(session) { impl ->
                impl.javaClass.getDeclaredField("encoderIdleGate").apply { isAccessible = true }
                    .set(impl, null)
            }
            var previous = snapshot(session)
            record(case, chunk, "initial", previous.values() + mapOf(
                "pcmSamples" to pcm.size,
                "pcmSha256" to digest(ByteBuffer.allocate(pcm.size * 2)
                    .order(ByteOrder.LITTLE_ENDIAN).apply { asShortBuffer().put(pcm) }.array()),
            ))
            var offset = 0
            while (offset < pcm.size) {
                val end = minOf(offset + chunk, pcm.size)
                session.acceptPcmShort(pcm.copyOfRange(offset, end))
                val current = snapshot(session)
                if (current.generation != previous.generation ||
                    current.streamStartSample != previous.streamStartSample
                ) {
                    record(case, chunk, "transition_observed", current.values() + mapOf(
                        "submittedSamples" to end,
                        "previousGeneration" to previous.generation,
                        "previousStreamStartSample" to previous.streamStartSample,
                    ))
                }
                previous = current
                offset = end
            }
            val beforeStop = previous
            val lastsBeforeStop = capture.lastCount()
            record(case, chunk, "before_stop", beforeStop.values() + mapOf("lastsBeforeStop" to lastsBeforeStop))
            session.stop()
            capture.awaitStopped()
            val finals = capture.finalResults()
            val text = finals.joinToString("") { it.text }
            val timestamps = finals.flatMap { it.timestamps }
            record(case, chunk, "stopped", capture.summary() + mapOf(
                "textLength" to text.length,
                "textSha256" to digest(text.toByteArray(Charsets.UTF_8)),
                "timestampCount" to timestamps.size,
                "timestamps" to timestamps,
                "finalBoundaries" to finals.map { result -> mapOf(
                    "isLast" to result.isLast,
                    "textLength" to result.text.length,
                    "textSha256" to digest(result.text.toByteArray(Charsets.UTF_8)),
                    "firstTimestamp" to result.timestamps.firstOrNull(),
                    "lastTimestamp" to result.timestamps.lastOrNull(),
                ) },
            ))
            assertEquals("no last final before explicit stop", 0, lastsBeforeStop)
            capture.assertTerminal()
            Run(beforeStop, text, timestamps)
        }
    }

    private data class Run(val beforeStop: Snapshot, val text: String, val timestamps: List<Float>)

    private data class Snapshot(val publicSamples: Long, val streamStartSample: Long, val generation: Long) {
        fun values(): Map<String, Any> = mapOf(
            "publicSamples" to publicSamples,
            "streamStartSample" to streamStartSample,
            "generation" to generation,
        )
    }

    private fun snapshot(session: AsrSession): Snapshot {
        var result: Snapshot? = null
        onDecoder(session) { impl ->
            fun field(name: String) = impl.javaClass.getDeclaredField(name)
                .apply { isAccessible = true }.get(impl)
            val generation = field("recognizerResetGeneration")!!
            result = Snapshot(
                (field("publicSamplesFed") as Number).toLong(),
                (field("streamStartSample") as Number).toLong(),
                (generation.javaClass.getDeclaredMethod("snapshot").apply { isAccessible = true }
                    .invoke(generation) as Number).toLong(),
            )
        }
        return checkNotNull(result)
    }

    /** Observe each submitted block after its decoder work, without an arbitrary sleep. */
    private fun onDecoder(session: AsrSession, action: (Any) -> Unit) {
        val impl = session.javaClass.getDeclaredField("impl").apply { isAccessible = true }.get(session)!!
        val handler = impl.javaClass.getDeclaredField("decoderHandler").apply { isAccessible = true }
            .get(impl) as Handler
        val done = CountDownLatch(1)
        var failure: Throwable? = null
        check(handler.post {
            try { action(impl) } catch (t: Throwable) { failure = t } finally { done.countDown() }
        }) { "decoder handler rejected the observation barrier" }
        assertTrue("decoder did not drain submitted PCM", done.await(45, TimeUnit.SECONDS))
        failure?.let { throw it }
    }

    private fun record(case: String, chunk: Int, event: String, values: Map<String, Any>) {
        report.appendText(JSONObject(values + mapOf(
            "case" to case, "chunkSamples" to chunk, "gateEnabled" to false,
            "numThreads" to 2, "event" to event,
        )).toString() + "\n")
    }

    private fun digest(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes)
        .joinToString("") { "%02x".format(it) }

    private class Capture : AsrCallback {
        private val finals = Collections.synchronizedList(mutableListOf<AsrResult>())
        private val events = Collections.synchronizedList(mutableListOf<String>())
        private val stopped = CountDownLatch(1)
        override fun onFinal(result: AsrResult) {
            finals.add(result)
            events.add(if (result.isLast) "last" else "final")
        }
        override fun onError(error: AsrError) { events.add("error"); stopped.countDown() }
        override fun onSessionStopped() { events.add("stopped"); stopped.countDown() }
        fun awaitStopped() = assertTrue("session did not stop", stopped.await(45, TimeUnit.SECONDS))
        fun finalResults(): List<AsrResult> = synchronized(finals) { finals.toList() }
        fun lastCount(): Int = synchronized(finals) { finals.count { it.isLast } }
        fun summary(): Map<String, Any> {
            val trace = synchronized(events) { events.toList() }
            return mapOf(
                "finals" to finalResults().size,
                "lasts" to lastCount(),
                "stopped" to trace.count { it == "stopped" },
                "errors" to trace.count { it == "error" },
                "callbackTrace" to trace,
            )
        }
        fun assertTerminal() {
            val trace = synchronized(events) { events.toList() }
            assertEquals("no ASR errors", 0, trace.count { it == "error" })
            assertEquals("exactly one last final", 1, lastCount())
            assertEquals("exactly one stopped callback", 1, trace.count { it == "stopped" })
            assertEquals("last must precede stopped", listOf("last", "stopped"), trace.takeLast(2))
        }
    }
}
