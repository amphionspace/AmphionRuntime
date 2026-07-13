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
import org.junit.Test

class AarMediumPlaybackRtf20DeviceTest {
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()
    private val outputDir = File(
        context.getExternalFilesDir(null) ?: context.filesDir,
        "aar-medium-playback-rtf20",
    ).apply { mkdirs() }
    private val runId = "aar-medium-playback-rtf20-${System.currentTimeMillis()}"

    @Test
    fun runMediumPlaybackRtf20() {
        TextToSpeechSdk.setWorkPath(File(context.cacheDir, "aar-medium-playback-rtf20-work").apply {
            deleteRecursively()
            mkdirs()
        }.absolutePath)

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

        try {
            repeat(WARMUP_RUNS) { warmupIndex ->
                runSpeak(engine, "warmup", warmupIndex)
                SystemClock.sleep(BETWEEN_RUN_SETTLE_MS)
            }

            repeat(REPEATS) { iteration ->
                val row = runSpeak(engine, "measure", iteration)
                rows += row
                resultsFile.appendText(row.toString() + "\n", Charsets.UTF_8)
                Log.i(TAG, "MEDIUM_PLAYBACK_RTF20 ${row.toString().replace('\n', ' ')}")
                SystemClock.sleep(BETWEEN_RUN_SETTLE_MS)
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
            .put("warmupRuns", WARMUP_RUNS)
            .put("text", MEDIUM_TEXT)
            .put("speed", SPEED.toDouble())
            .put("chunkSize", CHUNK_SIZE)
            .put("firstChunkSize", CHUNK_SIZE)
            .put("pcmQueueCapacity", PCM_QUEUE_CAPACITY)
            .put("resultsFile", resultsFile.absolutePath)
            .put("stats", summarize(rows))
        summaryFile.writeText(summary.toString(2) + "\n", Charsets.UTF_8)
        Log.i(TAG, "MEDIUM_PLAYBACK_RTF20_SUMMARY ${summary.toString().replace('\n', ' ')}")

        assertEquals("expected measured rows", REPEATS, rows.size)
        rows.forEach { row ->
            assertTrue("row errors: ${row.getJSONArray("errors")}", row.getJSONArray("errors").length() == 0)
            assertTrue("row did not complete playback: $row", row.getBoolean("playbackCompleted"))
        }
    }

    private fun runSpeak(
        engine: com.lits.tts.sdk.TextToSpeechEngine,
        group: String,
        iteration: Int,
    ): JSONObject {
        val listener = PlaybackListener()
        engine.setListener(listener)
        val requestId = "$runId-$group-$iteration"
        val submitAtMs = SystemClock.elapsedRealtime()
        engine.speak(MEDIUM_TEXT, speakParams(requestId))
        val completed = listener.playbackLatch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS)
        val parsed = parseProfiling(listener.profilingInfo)
        val modelMs = parsed.optLong("hiddenMs", 0L) + parsed.optLong("decoderMs", 0L) + parsed.optLong("vocoderMs", 0L)
        val audioDurationMs = listener.audioDurationMs
        return JSONObject()
            .put("runId", runId)
            .put("group", group)
            .put("iteration", iteration)
            .put("completed", completed)
            .put("playbackCompleted", listener.playbackCompleted)
            .put("submitToSynthesisCompleteMs", listener.synthesisCompleteAtMs - submitAtMs)
            .put("submitToPlaybackCompleteMs", listener.playbackCompleteAtMs - submitAtMs)
            .put("synthesisCompleteToPlaybackCompleteMs", listener.playbackCompleteAtMs - listener.synthesisCompleteAtMs)
            .put("firstPacketMs", listener.firstPacketMs)
            .put("playbackStartMs", listener.playbackStartMs)
            .put("synthesisMs", listener.synthesisMs)
            .put("audioDurationMs", audioDurationMs)
            .put("rtf", listener.rtf)
            .put("modelMs", modelMs)
            .put("modelRtf", if (audioDurationMs > 0) modelMs.toDouble() / audioDurationMs else -1.0)
            .put("profiling", parsed)
            .put("profilingInfo", listener.profilingInfo)
            .put("errors", JSONArray(listener.errors))
    }

    private fun speakParams(requestId: String): SpeakParams =
        SpeakParams(
            requestId = requestId,
            speed = SPEED,
            volume = VOLUME,
            pitch = PITCH,
            languageContext = LANGUAGE,
            playType = PlayType.SYNTHESIZE_AND_PLAY,
            queueMode = QueueMode.PREEMPT,
            streamingConfig = TtsStreamingConfig(
                chunkSize = CHUNK_SIZE,
                firstChunkSize = CHUNK_SIZE,
                pcmQueueCapacity = PCM_QUEUE_CAPACITY,
            ),
        )

    private fun parseProfiling(profilingInfo: String): JSONObject {
        val result = JSONObject()
        val frontendMatch = FRONTEND_PATTERN.matcher(profilingInfo)
        if (frontendMatch.find()) result.put("frontendMs", frontendMatch.group(1)!!.toLong())
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
        return result
    }

    private fun summarize(rows: List<JSONObject>): JSONObject {
        val rtfs = rows.map { it.getDouble("rtf") }.sorted()
        val modelRtfs = rows.map { it.getDouble("modelRtf") }.sorted()
        val decoderAvg = rows.map { it.getJSONObject("profiling").optDouble("decoderAvgMs", Double.NaN) }
            .filter { !it.isNaN() }
        val vocoderAvg = rows.map { it.getJSONObject("profiling").optDouble("vocoderAvgMs", Double.NaN) }
            .filter { !it.isNaN() }
        return JSONObject()
            .put("count", rows.size)
            .put("rtfMean", rtfs.average())
            .put("rtfP50", percentile(rtfs, 50.0))
            .put("rtfP90", percentile(rtfs, 90.0))
            .put("rtfMax", rtfs.lastOrNull() ?: -1.0)
            .put("modelRtfMean", modelRtfs.average())
            .put("modelRtfP50", percentile(modelRtfs, 50.0))
            .put("decoderAvgMsMean", decoderAvg.average())
            .put("vocoderAvgMsMean", vocoderAvg.average())
    }

    private fun percentile(values: List<Double>, percentile: Double): Double {
        if (values.isEmpty()) return Double.NaN
        val index = (values.size - 1) * percentile / 100.0
        val low = kotlin.math.floor(index).toInt()
        val high = kotlin.math.ceil(index).toInt()
        if (low == high) return values[low]
        return values[low] * (high - index) + values[high] * (index - low)
    }

    private class PlaybackListener : SpeakListener {
        val playbackLatch = CountDownLatch(1)
        val errors = mutableListOf<String>()
        var synthesisCompleteAtMs = -1L
        var playbackCompleteAtMs = -1L
        var playbackCompleted = false
        var firstPacketMs = -1L
        var playbackStartMs = -1L
        var synthesisMs = -1L
        var audioDurationMs = -1L
        var rtf = -1.0
        var profilingInfo = ""

        override fun onStart(requestId: String, response: StartResponse) = Unit

        override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) = Unit

        override fun onComplete(requestId: String, response: CompleteResponse) {
            if (response.type == CompleteType.SYNTHESIS_COMPLETE) {
                synthesisCompleteAtMs = SystemClock.elapsedRealtime()
                firstPacketMs = response.firstPacketMs
                playbackStartMs = response.playbackStartMs
                synthesisMs = response.synthesisMs
                audioDurationMs = response.audioDurationMs
                rtf = response.rtf
                profilingInfo = response.profilingInfo
            } else if (response.type == CompleteType.PLAYBACK_COMPLETE) {
                playbackCompleteAtMs = SystemClock.elapsedRealtime()
                playbackCompleted = true
                playbackLatch.countDown()
            }
        }

        override fun onStop(requestId: String, response: StopResponse) {
            errors += "$requestId:STOP:${response.message}"
            playbackLatch.countDown()
        }

        override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
            errors += "$requestId:$errorCode:$errorMessage"
            playbackLatch.countDown()
        }
    }

    private companion object {
        const val TAG = "AarMediumPlaybackRtf20"
        const val LANGUAGE = "zh-en"
        const val VOICE_ID = "lits-female-02"
        const val SPEED = 1.0f
        const val VOLUME = 1.0f
        const val PITCH = 1.0f
        const val CHUNK_SIZE = 50
        const val PCM_QUEUE_CAPACITY = 32
        const val WARMUP_RUNS = 3
        const val REPEATS = 20
        const val BETWEEN_RUN_SETTLE_MS = 1_000L
        const val FINAL_SETTLE_MS = 2_000L
        const val TIMEOUT_MS = 90_000L
        const val MEDIUM_TEXT = "这是一个用于测量实时率的稳定性测试句子，语音合成应该保持平稳。"
        val FRONTEND_PATTERN: Pattern = Pattern.compile("frontend=(\\d+)ms")
        val PROFILE_PATTERN: Pattern = Pattern.compile(
            "onnxHiddenEncoder=(\\d+)ms/(\\d+)x/[\\d.]+ms_avg onnxStreamDecoderChunk=(\\d+)ms/(\\d+)x/[\\d.]+ms_avg onnxVocoder=(\\d+)ms/(\\d+)x/[\\d.]+ms_avg",
        )
    }
}
