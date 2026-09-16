package com.lits.tts.aarhost

import android.os.Debug
import android.os.SystemClock
import androidx.test.platform.app.InstrumentationRegistry
import com.lits.tts.sdk.*
import java.io.File
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

/** Versioned student scenarios, independent of the legacy corpus and its expectations. */
class AarStudentStabilityDeviceTest {
    @get:Rule val resources = AarLicensedExternalResourcesRule()
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val runId = "student-stability-${System.currentTimeMillis()}"
    private val output = File(context.getExternalFilesDir(null), runId).apply { mkdirs() }
    private val recorder = Recorder()
    private var engine: TextToSpeechEngine? = null
    private var currentLanguage: String? = null
    private var submitted = 0

    @Test fun studentPublicApiStability() {
        val arguments = InstrumentationRegistry.getArguments()
        val limit = arguments.getString("caseLimit")?.toInt() ?: 1000
        require(limit in 1..1000)
        val started = SystemClock.elapsedRealtime()
        val sampling = AtomicBoolean(true)
        val sampler = Thread({
            while (sampling.get()) {
                File(output, "memory.jsonl").appendText(snapshot().toString() + "\n")
                Thread.sleep(1000)
            }
        }, "student-test-memory").apply { isDaemon = true; start() }
        var completed = 0
        var failure: Throwable? = null
        try {
            repeat(limit) { index ->
                val before = SystemClock.elapsedRealtime()
                val firstRecord = recorder.order.size
                val kind = KINDS[index % KINDS.size]
                var caseFailure: Throwable? = null
                try {
                    runScenario(index, kind)
                    assertTrue("Callback violations: ${recorder.violations}", recorder.violations.isEmpty())
                } catch (error: Throwable) {
                    caseFailure = error
                    throw error
                } finally {
                    val records = recorder.order.drop(firstRecord)
                    File(output, "results.jsonl").appendText(JSONObject()
                        .put("index", index).put("scenario", kind).put("chunkSize", chunk(index))
                        .put("status", if (caseFailure == null) "PASS" else "FAIL")
                        .put("error", caseFailure?.toString() ?: JSONObject.NULL)
                        .put("elapsedMs", SystemClock.elapsedRealtime() - before)
                        .put("requests", JSONArray(records.map { it.json() }))
                        .put("memory", snapshot()).toString() + "\n")
                }
                completed++
            }
        } catch (error: Throwable) {
            failure = error
        } finally {
            runCatching { engine?.shutdown() }.onFailure { if (failure == null) failure = it }
            engine = null
            // Observe asynchronous release and late callbacks after the last scenario.
            SystemClock.sleep(3000)
            sampling.set(false)
            sampler.join()
            if (failure == null && recorder.violations.isNotEmpty()) {
                failure = AssertionError(recorder.violations.joinToString())
            }
            File(output, "requests-final.jsonl").writeText(recorder.order.joinToString("\n", postfix = "\n") { it.json().toString() })
            File(output, "summary.json").writeText(JSONObject()
                .put("profile", "student-public-api-v1").put("runId", runId)
                .put("plannedCases", limit).put("passedCases", completed)
                .put("submittedRequests", submitted).put("completedFull1000", completed == 1000 && failure == null)
                .put("status", if (failure == null) "PASS" else "FAIL")
                .put("failure", failure?.toString() ?: JSONObject.NULL)
                .put("callbackViolations", JSONArray(recorder.violations))
                .put("elapsedMs", SystemClock.elapsedRealtime() - started)
                .put("finalMemory", snapshot()).toString(2))
        }
        failure?.let { throw AssertionError("$runId failed; evidence: $output", it) }
        assertEquals(limit, completed)
    }

    private fun runScenario(index: Int, kind: String) {
        val language = if (kind == "english") "en-US" else "zh-en"
        val active = getEngine(language)
        val prefix = "case-$index"
        val phrase = when (kind) {
            "english" -> "The morning light falls quietly across the room. Test number ${index + 1}."
            "mixed" -> "提示：Hello world。第${index + 1}次测试，电量百分之八十。"
            "long" -> "清晨的光穿过窗户，落在尚未读完的书页上。人需要在有限的时间里思考，理解自己，也理解他人。".repeat(4) + " This is the final sentence."
            else -> "第${index + 1}次测试。今天阳光明媚，我们一起出发。"
        }
        when (kind) {
            "queue" -> {
                val a = add("$prefix-a"); val b = add("$prefix-b")
                speak(active, a, phrase, params(a, index))
                speak(active, b, "第二条请求。", params(b, index))
                a.await(); b.await(); a.assertSynthesis(); b.assertSynthesis()
                assertTrue("Queue started before predecessor completed", a.terminalOrdinal < b.startOrdinal)
            }
            "preempt", "stop", "shutdown" -> {
                val a = add("$prefix-active"); val b = if (kind == "stop") add("$prefix-queued") else null
                val next = if (kind == "preempt") add("$prefix-replacement") else null
                val once = AtomicBoolean(false)
                recorder.afterData = { id ->
                    if (id == a.id && once.compareAndSet(false, true)) {
                        when (kind) {
                            "preempt" -> speak(active, next!!, "替换后的请求。", params(next, index).copy(queueMode = QueueMode.PREEMPT))
                            "stop" -> {
                                speak(active, b!!, "这条等待中的请求应该被停止。", params(b, index))
                                active.stop()
                            }
                            "shutdown" -> active.shutdown()
                        }
                    }
                }
                try {
                    // More than one chunk, so cancellation occurs while synthesis is active.
                    speak(active, a, phrase.repeat(8), params(a, index))
                    a.await(); assertTrue("Cancellation action never executed", once.get())
                    a.assertStopped()
                    b?.let { it.await(); it.assertStopped(); assertEquals(0, it.events.count { e -> e == "start" }) }
                    next?.let { it.await(); it.assertSynthesis() }
                } finally { recorder.afterData = null }
                if (kind == "shutdown") {
                    assertEquals(TtsErrorCode.ENGINE_DESTROYED, assertThrows(TextToSpeechException::class.java) { active.isBusy() }.errorCode)
                    engine = null; currentLanguage = null
                }
                val recovery = add("$prefix-recovery")
                speak(getEngine(language), recovery, "恢复正常。", params(recovery, index))
                recovery.await(); recovery.assertSynthesis()
                a.assertStopped(); b?.assertStopped()
            }
            "playback" -> {
                val r = add(prefix, playback = true)
                speak(active, r, "播放测试。Hello.", params(r, index).copy(playType = PlayType.SYNTHESIZE_AND_PLAY))
                r.await(); r.assertPlayback()
            }
            "invalid-recovery" -> {
                val r = add("$prefix-invalid")
                val variant = (index / KINDS.size) % 3
                val invalid = when (variant) {
                    0 -> params(r, index).copy(volume = -1f)
                    1 -> params(r, index).copy(streamingConfig = TtsStreamingConfig(chunkSize = 32))
                    else -> params(r, index)
                }
                speak(active, r, if (variant == 2) " " else phrase, invalid)
                r.await()
                assertEquals(if (variant == 2) TtsErrorCode.TEXT_LENGTH_INVALID else TtsErrorCode.RUNTIME_EXCEPTION, r.errorCode)
                // Chunk compatibility is checked after the synthesis worker starts;
                // malformed public scalar/text parameters are rejected before start.
                assertEquals(if (variant == 1) listOf("start", "error") else listOf("error"), r.events.toList())
                val good = add("$prefix-recovery")
                speak(active, good, "有效请求可以继续。", params(good, index)); good.await(); good.assertSynthesis()
            }
            else -> {
                val r = add(prefix)
                speak(active, r, phrase, params(r, index).copy(languageContext = language))
                r.await(); r.assertSynthesis()
            }
        }
    }

    private fun getEngine(language: String): TextToSpeechEngine {
        if (currentLanguage != language) {
            engine?.shutdown(); engine = null
        }
        if (engine == null) {
            engine = TextToSpeechSdk.createEngine(CreateEngineParams(language, RunMode.OFFLINE, "lits-female-02"))
            currentLanguage = language
            engine!!.setListener(recorder)
        }
        return engine!!
    }
    private fun chunk(index: Int) = CHUNKS[(index / KINDS.size + index) % CHUNKS.size]
    private fun params(record: Record, index: Int) = SpeakParams(record.id,
        playType = PlayType.SYNTHESIZE_ONLY, queueMode = QueueMode.QUEUE,
        speed = listOf(.8f, 1f, 1.2f)[index % 3], volume = if (index % 2 == 0) 1f else .5f,
        streamingConfig = TtsStreamingConfig(chunkSize = chunk(index), pcmQueueCapacity = if ((index / KINDS.size) % 2 == 0) 1 else 32))
    private fun add(id: String, playback: Boolean = false) = recorder.add(id, playback)
    private fun speak(engine: TextToSpeechEngine, r: Record, text: String, params: SpeakParams) {
        r.input = text; r.parameters = params.toString(); submitted++
        engine.speak(text, params)
    }

    private class Recorder : SpeakListener {
        val order = CopyOnWriteArrayList<Record>()
        val records = ConcurrentHashMap<String, Record>()
        val violations = CopyOnWriteArrayList<String>()
        private var ordinal = 0L
        @Volatile var afterData: ((String) -> Unit)? = null
        fun add(id: String, playback: Boolean): Record = Record(id, playback).also {
            check(records.putIfAbsent(id, it) == null); order += it
        }
        @Synchronized private fun event(id: String, value: String): Record {
            val r = records.getValue(id)
            if (r.terminalOrdinal >= 0) violations += "$id callback after terminal: $value"
            r.events += value
            r.timeline += "${SystemClock.elapsedRealtime()}:$value"
            ordinal++
            if (value == "start") r.startOrdinal = ordinal
            if (value == "stop" || value == "error" || value == "complete:PLAYBACK_COMPLETE" ||
                (!r.playback && value == "complete:SYNTHESIS_COMPLETE")) r.terminalOrdinal = ordinal
            return r
        }
        override fun onStart(requestId: String, response: StartResponse) {
            records.getValue(requestId).start = response; event(requestId, "start")
        }
        override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) {
            val r = event(requestId, "data")
            if (response.sequence != r.chunks || !response.isStreaming || audio.size % 2 != 0) violations += "$requestId invalid PCM/chunk sequence"
            r.chunks++; r.bytes += audio.size
            runCatching { afterData?.invoke(requestId) }.onFailure {
                violations += "$requestId callback action failed: $it"; r.done.countDown()
            }
        }
        override fun onPlaybackStart(requestId: String, elapsedMs: Long) { event(requestId, "playback-start") }
        override fun onComplete(requestId: String, response: CompleteResponse) {
            val r = event(requestId, "complete:${response.type}")
            if (response.type == CompleteType.SYNTHESIS_COMPLETE) r.complete = response
            if (r.terminalOrdinal >= 0) r.done.countDown()
        }
        override fun onStop(requestId: String, response: StopResponse) { event(requestId, "stop").done.countDown() }
        override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
            val r = event(requestId, "error"); r.errorCode = errorCode; r.error = errorMessage; r.done.countDown()
        }
    }

    private class Record(val id: String, val playback: Boolean) {
        val events = CopyOnWriteArrayList<String>()
        val timeline = CopyOnWriteArrayList<String>()
        val done = CountDownLatch(1)
        var input = ""; var parameters = ""
        var start: StartResponse? = null; var complete: CompleteResponse? = null
        var errorCode: Int? = null; var error: String? = null
        var bytes = 0L; var chunks = 0
        var startOrdinal = -1L; var terminalOrdinal = -1L
        fun await() { assertTrue("$id timeout: $events", done.await(120, TimeUnit.SECONDS)) }
        fun assertSynthesis() {
            assertNull("$id: $error", errorCode)
            assertEquals("$id", "start", events.firstOrNull())
            assertEquals(1, events.count { it == "start" })
            assertEquals(1, events.count { it == "complete:SYNTHESIS_COMPLETE" })
            assertFalse(events.contains("stop")); assertFalse(events.contains("playback-start"))
            assertEquals("complete:SYNTHESIS_COMPLETE", events.lastOrNull())
            assertTrue("$id no PCM", bytes > 0); assertFormat()
        }
        fun assertStopped() {
            assertNull("$id: $error", errorCode)
            assertEquals(1, events.count { it == "stop" })
            assertFalse(events.any { it.startsWith("complete:") }); assertEquals("stop", events.lastOrNull())
        }
        fun assertPlayback() {
            assertNull("$id: $error", errorCode); assertEquals(0L, bytes); assertFormat()
            // Production and playback run concurrently; only their shared boundaries are ordered.
            assertEquals(4, events.size)
            for (event in listOf("start", "playback-start", "complete:SYNTHESIS_COMPLETE", "complete:PLAYBACK_COMPLETE")) {
                assertEquals(event, 1, events.count { it == event })
            }
            assertEquals("start", events.first())
            assertEquals("complete:PLAYBACK_COMPLETE", events.last())
        }
        private fun assertFormat() {
            assertEquals(24000, start?.sampleRate); assertEquals(16, start?.sampleBit)
            assertEquals(1, start?.audioChannel); assertEquals(true, start?.isStreaming)
        }
        fun json() = JSONObject().put("id", id).put("text", input).put("params", parameters)
            .put("events", JSONArray(events)).put("timeline", JSONArray(timeline))
            .put("bytes", bytes).put("chunks", chunks).put("errorCode", errorCode).put("error", error)
            .put("firstPacketMs", complete?.firstPacketMs).put("synthesisMs", complete?.synthesisMs)
            .put("audioDurationMs", complete?.audioDurationMs).put("rtf", complete?.rtf)
    }

    private fun snapshot(): JSONObject {
        val status = File("/proc/self/status").readLines().mapNotNull { line ->
            val pair = line.split(':', limit = 2)
            if (pair.size == 2) pair[0] to pair[1].trim().substringBefore(' ').toLongOrNull() else null
        }.toMap()
        val runtime = Runtime.getRuntime()
        return JSONObject().put("elapsedRealtimeMs", SystemClock.elapsedRealtime())
            .put("rssKb", status["VmRSS"]).put("peakRssKb", status["VmHWM"])
            .put("threads", status["Threads"]).put("fds", File("/proc/self/fd").list()?.size)
            .put("javaHeapBytes", runtime.totalMemory() - runtime.freeMemory())
            .put("nativeHeapBytes", Debug.getNativeHeapAllocatedSize())
    }

    private companion object {
        val KINDS = listOf("chinese", "english", "mixed", "long", "queue", "preempt", "stop", "shutdown", "playback", "invalid-recovery")
        val CHUNKS = listOf(40, 50, 64, 75, 100, 150, 200)
    }
}
