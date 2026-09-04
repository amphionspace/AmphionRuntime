package com.lits.tts.aarhost

import android.os.SystemClock
import android.util.Log
import androidx.test.core.app.ApplicationProvider
import com.lits.tts.sdk.CompleteResponse
import com.lits.tts.sdk.CompleteType
import com.lits.tts.sdk.CreateEngineParams
import com.lits.tts.sdk.PlayType
import com.lits.tts.sdk.QueueMode
import com.lits.tts.sdk.RunMode
import com.lits.tts.sdk.SpeakListener
import com.lits.tts.sdk.SpeakParams
import com.lits.tts.sdk.StartResponse
import com.lits.tts.sdk.StopResponse
import com.lits.tts.sdk.SynthesisResponse
import com.lits.tts.sdk.TextToSpeechSdk
import com.lits.tts.sdk.TtsStreamingConfig
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.regex.Pattern
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class AarRtfAuditDeviceTest {
    @get:Rule
    val externalResources = AarLicensedExternalResourcesRule()

    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()
    private val outputDir = File(
        context.getExternalFilesDir(null) ?: context.filesDir,
        "aar-rtf-audit",
    ).apply { mkdirs() }
    private val runId = "aar-rtf-audit-${System.currentTimeMillis()}"

    @Test
    fun auditSharedEngineRtf() {
        val resultsFile = File(outputDir, "results-$runId.jsonl")
        val summaryFile = File(outputDir, "summary-$runId.json")
        val createStartMs = SystemClock.elapsedRealtime()
        val engine = TextToSpeechSdk.createEngine(
            CreateEngineParams(
                language = LANGUAGE,
                mode = RunMode.OFFLINE,
                voiceId = VOICE_ID,
                engineName = runId,
                modelLoadOnCreate = true,
            ),
        )
        val createEngineMs = SystemClock.elapsedRealtime() - createStartMs
        val rows = mutableListOf<JSONObject>()
        val errors = mutableListOf<String>()

        try {
            repeat(WARMUP_RUNS) { warmupIndex ->
                runSpeak(
                    engine = engine,
                    group = "warmup",
                    textName = "warmup",
                    text = WARMUP_TEXT,
                    playType = PlayType.SYNTHESIZE_ONLY,
                    iteration = warmupIndex,
                )
            }

            TEST_TEXTS.forEach { (textName, text) ->
                TEST_PLAY_TYPES.forEach { playType ->
                    repeat(REPEATS) { iteration ->
                        val row = runSpeak(engine, "measure", textName, text, playType, iteration)
                        rows += row
                        resultsFile.appendText(row.toString() + "\n", Charsets.UTF_8)
                        if (row.getJSONArray("errors").length() > 0) {
                            errors += "${row.getString("condition")}: ${row.getJSONArray("errors")}"
                        }
                        Log.i(TAG, "RESULT ${row.toString().replace('\n', ' ')}")
                        SystemClock.sleep(BETWEEN_RUN_SETTLE_MS)
                    }
                }
            }
        } finally {
            runCatching { engine.shutdown() }
            System.gc()
            SystemClock.sleep(FINAL_SETTLE_MS)
        }

        val summary = JSONObject()
            .put("runId", runId)
            .put("createEngineMs", createEngineMs)
            .put("repeats", REPEATS)
            .put("chunkSize", CHUNK_SIZE)
            .put("pcmQueueCapacity", PCM_QUEUE_CAPACITY)
            .put("speed", SPEED.toDouble())
            .put("resultsFile", resultsFile.absolutePath)
            .put("conditions", summarize(rows))
            .put("errors", JSONArray(errors))
        summaryFile.writeText(summary.toString(2) + "\n", Charsets.UTF_8)
        Log.i(TAG, "SUMMARY ${summary.toString().replace('\n', ' ')}")

        assertTrue("audit errors: $errors", errors.isEmpty())
        assertEquals("expected measured rows", TEST_TEXTS.size * TEST_PLAY_TYPES.size * REPEATS, rows.size)
    }

    @Test
    fun auditMediumSynthesizeOnlyRtf20() {
        val mediumOnlyRunId = "$runId-medium-synth-only"
        val resultsFile = File(outputDir, "results-$mediumOnlyRunId.jsonl")
        val summaryFile = File(outputDir, "summary-$mediumOnlyRunId.json")
        val createStartMs = SystemClock.elapsedRealtime()
        val engine = TextToSpeechSdk.createEngine(
            CreateEngineParams(
                language = LANGUAGE,
                mode = RunMode.OFFLINE,
                voiceId = VOICE_ID,
                engineName = mediumOnlyRunId,
                modelLoadOnCreate = true,
            ),
        )
        val createEngineMs = SystemClock.elapsedRealtime() - createStartMs
        val rows = mutableListOf<JSONObject>()

        try {
            repeat(WARMUP_RUNS) { warmupIndex ->
                runSpeak(
                    engine = engine,
                    group = "warmup",
                    textName = "warmup",
                    text = WARMUP_TEXT,
                    playType = PlayType.SYNTHESIZE_ONLY,
                    iteration = warmupIndex,
                )
            }

            repeat(REPEATS) { iteration ->
                val row = runSpeak(
                    engine = engine,
                    group = "measure",
                    textName = "medium",
                    text = MEDIUM_TEXT,
                    playType = PlayType.SYNTHESIZE_ONLY,
                    iteration = iteration,
                )
                rows += row
                resultsFile.appendText(row.toString() + "\n", Charsets.UTF_8)
                Log.i(TAG, "MEDIUM_ONLY ${row.toString().replace('\n', ' ')}")
                SystemClock.sleep(BETWEEN_RUN_SETTLE_MS)
            }
        } finally {
            runCatching { engine.shutdown() }
            System.gc()
            SystemClock.sleep(FINAL_SETTLE_MS)
        }

        val summary = JSONObject()
            .put("runId", mediumOnlyRunId)
            .put("createEngineMs", createEngineMs)
            .put("repeats", REPEATS)
            .put("chunkSize", CHUNK_SIZE)
            .put("firstChunkSize", CHUNK_SIZE)
            .put("pcmQueueCapacity", PCM_QUEUE_CAPACITY)
            .put("speed", SPEED.toDouble())
            .put("textName", "medium")
            .put("playType", PlayType.SYNTHESIZE_ONLY.name)
            .put("resultsFile", resultsFile.absolutePath)
            .put("conditions", summarize(rows))
        summaryFile.writeText(summary.toString(2) + "\n", Charsets.UTF_8)
        Log.i(TAG, "MEDIUM_ONLY_SUMMARY ${summary.toString().replace('\n', ' ')}")

        assertTrue("medium-only rows should not be empty", rows.isNotEmpty())
        assertEquals("expected measured rows", REPEATS, rows.size)
        rows.forEach { row ->
            assertTrue("medium-only row errors: ${row.getJSONArray("errors")}", row.getJSONArray("errors").length() == 0)
        }
    }

    @Test
    fun auditMediumPlaybackRtf20() {
        val playbackRunId = "$runId-medium-playback"
        val resultsFile = File(outputDir, "results-$playbackRunId.jsonl")
        val summaryFile = File(outputDir, "summary-$playbackRunId.json")
        val createStartMs = SystemClock.elapsedRealtime()
        val engine = TextToSpeechSdk.createEngine(
            CreateEngineParams(
                language = LANGUAGE,
                mode = RunMode.OFFLINE,
                voiceId = VOICE_ID,
                engineName = playbackRunId,
                modelLoadOnCreate = true,
            ),
        )
        val createEngineMs = SystemClock.elapsedRealtime() - createStartMs
        val rows = mutableListOf<JSONObject>()

        try {
            repeat(WARMUP_RUNS) { warmupIndex ->
                runSpeak(
                    engine = engine,
                    group = "warmup",
                    textName = "warmup",
                    text = WARMUP_TEXT,
                    playType = PlayType.SYNTHESIZE_AND_PLAY,
                    iteration = warmupIndex,
                )
            }

            repeat(REPEATS) { iteration ->
                val row = runSpeak(
                    engine = engine,
                    group = "measure",
                    textName = "medium",
                    text = MEDIUM_TEXT,
                    playType = PlayType.SYNTHESIZE_AND_PLAY,
                    iteration = iteration,
                )
                rows += row
                resultsFile.appendText(row.toString() + "\n", Charsets.UTF_8)
                Log.i(TAG, "MEDIUM_PLAYBACK ${row.toString().replace('\n', ' ')}")
                SystemClock.sleep(BETWEEN_RUN_SETTLE_MS)
            }
        } finally {
            runCatching { engine.shutdown() }
            System.gc()
            SystemClock.sleep(FINAL_SETTLE_MS)
        }

        val summary = JSONObject()
            .put("runId", playbackRunId)
            .put("createEngineMs", createEngineMs)
            .put("repeats", REPEATS)
            .put("chunkSize", CHUNK_SIZE)
            .put("firstChunkSize", CHUNK_SIZE)
            .put("pcmQueueCapacity", PCM_QUEUE_CAPACITY)
            .put("speed", SPEED.toDouble())
            .put("textName", "medium")
            .put("playType", PlayType.SYNTHESIZE_AND_PLAY.name)
            .put("resultsFile", resultsFile.absolutePath)
            .put("conditions", summarize(rows))
        summaryFile.writeText(summary.toString(2) + "\n", Charsets.UTF_8)
        Log.i(TAG, "MEDIUM_PLAYBACK_SUMMARY ${summary.toString().replace('\n', ' ')}")

        assertTrue("medium-playback rows should not be empty", rows.isNotEmpty())
        assertEquals("expected measured rows", REPEATS, rows.size)
        rows.forEach { row ->
            assertTrue("medium-playback row errors: ${row.getJSONArray("errors")}", row.getJSONArray("errors").length() == 0)
        }
    }

    private fun runSpeak(
        engine: com.lits.tts.sdk.TextToSpeechEngine,
        group: String,
        textName: String,
        text: String,
        playType: PlayType,
        iteration: Int,
    ): JSONObject {
        val listener = AuditListener()
        engine.setListener(listener)
        val requestId = "$runId-$group-$textName-${playType.name.lowercase()}-$iteration"
        val submitAtMs = SystemClock.elapsedRealtime()
        engine.speak(text, speakParams(requestId, playType))
        val completed = listener.terminalLatch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS)
        val parsed = parseProfiling(listener.profilingInfo)
        val modelMs = parsed.optLong("hiddenMs", 0L) + parsed.optLong("decoderMs", 0L) + parsed.optLong("vocoderMs", 0L)
        val audioDurationMs = listener.audioDurationMs
        return JSONObject()
            .put("runId", runId)
            .put("group", group)
            .put("condition", "$textName/${playType.name}")
            .put("textName", textName)
            .put("textLength", text.length)
            .put("playType", playType.name)
            .put("iteration", iteration)
            .put("completed", completed)
            .put("submitToCompleteMs", listener.completeAtMs - submitAtMs)
            .put("startCallbacks", listener.startCallbacks)
            .put("dataCallbacks", listener.dataCallbacks)
            .put("bytes", listener.bytes)
            .put("firstPacketMs", listener.firstPacketMs)
            .put("synthesisMs", listener.synthesisMs)
            .put("audioDurationMs", audioDurationMs)
            .put("rtf", listener.rtf)
            .put("modelMs", modelMs)
            .put("modelRtf", if (audioDurationMs > 0) modelMs.toDouble() / audioDurationMs else -1.0)
            .put("nonModelMs", if (listener.synthesisMs > modelMs) listener.synthesisMs - modelMs else 0L)
            .put("profiling", parsed)
            .put("profilingInfo", listener.profilingInfo)
            .put("errors", JSONArray(listener.errors))
    }

    private fun speakParams(requestId: String, playType: PlayType): SpeakParams =
        SpeakParams(
            requestId = requestId,
            speed = SPEED,
            volume = VOLUME,
            pitch = PITCH,
            languageContext = LANGUAGE,
            playType = playType,
            queueMode = QueueMode.PREEMPT,
            streamingConfig = TtsStreamingConfig(
                chunkSize = CHUNK_SIZE,
                firstChunkSize = CHUNK_SIZE,
                pcmQueueCapacity = PCM_QUEUE_CAPACITY,
            ),
        )

    private fun parseProfiling(profilingInfo: String): JSONObject {
        val result = JSONObject()
        val match = PROFILE_PATTERN.matcher(profilingInfo)
        if (match.find()) {
            val hiddenMs = match.group(1)!!.toLong()
            val hiddenCalls = match.group(2)!!.toInt()
            val decoderMs = match.group(3)!!.toLong()
            val decoderCalls = match.group(4)!!.toInt()
            val vocoderMs = match.group(5)!!.toLong()
            val vocoderCalls = match.group(6)!!.toInt()
            result
                .put("hiddenMs", hiddenMs)
                .put("hiddenCalls", hiddenCalls)
                .put("decoderMs", decoderMs)
                .put("decoderCalls", decoderCalls)
                .put("vocoderMs", vocoderMs)
                .put("vocoderCalls", vocoderCalls)
                .put("decoderAvgMs", decoderMs.toDouble() / decoderCalls.toDouble())
                .put("vocoderAvgMs", vocoderMs.toDouble() / vocoderCalls.toDouble())
        }
        val chunkMatch = CHUNK_PATTERN.matcher(profilingInfo)
        if (chunkMatch.find()) {
            result
                .put("chunks", chunkMatch.group(1)!!.toInt())
                .put("melLength", chunkMatch.group(2)!!.toInt())
                .put("chunkSize", chunkMatch.group(3)!!.toInt())
        }
        return result
    }

    private fun summarize(rows: List<JSONObject>): JSONObject {
        val result = JSONObject()
        rows.groupBy { it.getString("condition") }.toSortedMap().forEach { (condition, conditionRows) ->
            val rtfs = conditionRows.map { it.getDouble("rtf") }.sorted()
            val modelRtfs = conditionRows.map { it.getDouble("modelRtf") }.sorted()
            val firstPackets = conditionRows.map { it.getLong("firstPacketMs") }.sorted()
            result.put(
                condition,
                JSONObject()
                    .put("count", conditionRows.size)
                    .put("rtfMean", rtfs.average())
                    .put("rtfP50", percentile(rtfs, 50.0))
                    .put("rtfP90", percentile(rtfs, 90.0))
                    .put("rtfMax", rtfs.last())
                    .put("modelRtfMean", modelRtfs.average())
                    .put("modelRtfP50", percentile(modelRtfs, 50.0))
                    .put("firstPacketP50", percentileLong(firstPackets, 50.0))
                    .put("firstPacketP90", percentileLong(firstPackets, 90.0)),
            )
        }
        return result
    }

    private fun percentile(values: List<Double>, percentile: Double): Double {
        if (values.isEmpty()) return Double.NaN
        val index = (values.size - 1) * percentile / 100.0
        val low = kotlin.math.floor(index).toInt()
        val high = kotlin.math.ceil(index).toInt()
        if (low == high) return values[low]
        return values[low] * (high - index) + values[high] * (index - low)
    }

    private fun percentileLong(values: List<Long>, percentile: Double): Double =
        percentile(values.map { it.toDouble() }, percentile)

    private class AuditListener : SpeakListener {
        val terminalLatch = CountDownLatch(1)
        val errors = mutableListOf<String>()
        var startCallbacks = 0
        var dataCallbacks = 0
        var bytes = 0L
        var completeAtMs = -1L
        var firstPacketMs = -1L
        var synthesisMs = -1L
        var audioDurationMs = -1L
        var rtf = -1.0
        var profilingInfo = ""

        override fun onStart(requestId: String, response: StartResponse) {
            startCallbacks += 1
        }

        override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) {
            dataCallbacks += 1
            bytes += audio.size
        }

        override fun onComplete(requestId: String, response: CompleteResponse) {
            if (response.type == CompleteType.SYNTHESIS_COMPLETE || completeAtMs < 0L) {
                completeAtMs = SystemClock.elapsedRealtime()
                firstPacketMs = response.firstPacketMs
                synthesisMs = response.synthesisMs
                audioDurationMs = response.audioDurationMs
                rtf = response.rtf
                profilingInfo = response.profilingInfo
                terminalLatch.countDown()
            }
        }

        override fun onStop(requestId: String, response: StopResponse) = Unit

        override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
            errors += "$requestId:$errorCode:$errorMessage"
            terminalLatch.countDown()
        }
    }

    private companion object {
        const val TAG = "AarRtfAudit"
        const val LANGUAGE = "zh-en"
        const val VOICE_ID = "lits-female-02"
        const val SPEED = 1.0f
        const val VOLUME = 1.0f
        const val PITCH = 1.0f
        const val CHUNK_SIZE = 50
        const val PCM_QUEUE_CAPACITY = 32
        const val WARMUP_RUNS = 3
        const val REPEATS = 20
        const val BETWEEN_RUN_SETTLE_MS = 120L
        const val FINAL_SETTLE_MS = 2_000L
        const val TIMEOUT_MS = 60_000L
        const val WARMUP_TEXT = "预热。"
        const val MEDIUM_TEXT = "这是一个用于测量实时率的稳定性测试句子，语音合成应该保持平稳。"
        val TEST_TEXTS = listOf(
            "short" to "测",
            "medium" to MEDIUM_TEXT,
        )
        val TEST_PLAY_TYPES = listOf(PlayType.SYNTHESIZE_ONLY, PlayType.SYNTHESIZE_AND_PLAY)
        val PROFILE_PATTERN: Pattern = Pattern.compile(
            "onnxHiddenEncoder=(\\d+)ms/(\\d+)x/[\\d.]+ms_avg onnxStreamDecoderChunk=(\\d+)ms/(\\d+)x/[\\d.]+ms_avg onnxVocoder=(\\d+)ms/(\\d+)x/[\\d.]+ms_avg",
        )
        val CHUNK_PATTERN: Pattern = Pattern.compile("chunks=(\\d+) melLength=(\\d+) chunkSize=(\\d+)")
    }
}
