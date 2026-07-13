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
import com.lits.tts.sdk.TextToSpeechEngine
import com.lits.tts.sdk.TextToSpeechSdk
import com.lits.tts.sdk.TtsStreamingConfig
import java.io.File
import java.util.Locale
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AarInterfaceMultiSpeakThermalRtfTest {
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()
    private val outputDir = File(
        context.getExternalFilesDir(null) ?: context.filesDir,
        "aar-multi-speak-thermal-rtf",
    ).apply { mkdirs() }
    private val runId = "aar-multi-speak-thermal-rtf-${System.currentTimeMillis()}"

    @Test
    fun multiSentenceRepeatedSpeakReportsRtfDriftAndAudibleGapLatency() {
        val samples = buildSamples()
        assertEquals(SENTENCE_COUNT, samples.size)

        TextToSpeechSdk.setWorkPath(File(context.cacheDir, "aar-multi-speak-work").apply {
            deleteRecursively()
            mkdirs()
        }.absolutePath)

        val engineStartMs = SystemClock.elapsedRealtime()
        val engine = TextToSpeechSdk.createEngine(
            CreateEngineParams(
                language = LANGUAGE,
                mode = RunMode.OFFLINE,
                voiceId = VOICE_ID,
                engineName = runId,
            ),
        )
        val createEngineMs = SystemClock.elapsedRealtime() - engineStartMs
        val results = mutableListOf<SpeakResult>()

        try {
            runWarmup(engine)
            repeat(ROUND_COUNT) { roundIndex ->
                samples.forEachIndexed { sentenceIndex, text ->
                    val previousPlaybackCompleteAtMs = results.lastOrNull()?.playbackCompleteAtMs ?: -1L
                    val caseId = "round-${roundIndex + 1}-sentence-${sentenceIndex + 1}"
                    val result = runSpeak(engine, caseId, text, previousPlaybackCompleteAtMs)
                    results += result
                    Log.i(TAG, result.toLogLine())
                    Thread.sleep(INTER_SPEAK_SLEEP_MS)
                }
            }
        } finally {
            runCatching { engine.shutdown() }
        }

        writeArtifacts(createEngineMs, results)
        assertTrue("unexpected AAR multi-speak errors: ${results.flatMap { it.errors }}", results.all { it.errors.isEmpty() })
        assertEquals("speak count", ROUND_COUNT * SENTENCE_COUNT, results.size)
    }

    private fun runWarmup(engine: TextToSpeechEngine) {
        val listener = SingleSpeakListener("warmup")
        engine.setListener(listener)
        engine.speak("这是 AAR 多轮连续播报压测的预热句。", speakParams("warmup-$runId"))
        assertTrue("warmup playback complete timeout", listener.playbackCompleteLatch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS))
    }

    private fun runSpeak(
        engine: TextToSpeechEngine,
        caseId: String,
        text: String,
        previousPlaybackCompleteAtMs: Long,
    ): SpeakResult {
        val listener = SingleSpeakListener(caseId)
        engine.setListener(listener)
        val before = DeviceSnapshot.capture()
        val submitAtMs = SystemClock.elapsedRealtime()
        engine.speak(text, speakParams("$caseId-$runId"))
        val completed = listener.playbackCompleteLatch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS)
        val after = DeviceSnapshot.capture()

        val playbackCompleteAtMs = listener.playbackCompleteAtMs
        val audibleGapMs = if (previousPlaybackCompleteAtMs >= 0L && listener.firstPacketMs >= 0L) {
            submitAtMs + listener.firstPacketMs - previousPlaybackCompleteAtMs
        } else {
            -1L
        }

        return SpeakResult(
            caseId = caseId,
            text = text,
            submitAtMs = submitAtMs,
            submitToStartMs = listener.startAtMs - submitAtMs,
            firstPacketMs = listener.firstPacketMs,
            synthesisMs = listener.synthesisMs,
            audioDurationMs = listener.audioDurationMs,
            rtf = listener.rtf,
            submitToPlaybackCompleteMs = if (playbackCompleteAtMs >= 0L) playbackCompleteAtMs - submitAtMs else -1L,
            previousPlaybackCompleteToFirstPacketMs = audibleGapMs,
            playbackCompleteAtMs = playbackCompleteAtMs,
            completed = completed,
            cpuBefore = before,
            cpuAfter = after,
            errors = listener.errors.toList(),
        )
    }

    private fun speakParams(requestId: String): SpeakParams =
        SpeakParams(
            requestId = requestId,
            speed = 1.0f,
            playType = PlayType.SYNTHESIZE_AND_PLAY,
            queueMode = QueueMode.PREEMPT,
            languageContext = LANGUAGE,
            streamingConfig = TtsStreamingConfig(
                chunkSize = CHUNK_SIZE,
                pcmQueueCapacity = PCM_QUEUE_CAPACITY,
            ),
        )

    private fun writeArtifacts(createEngineMs: Long, results: List<SpeakResult>) {
        File(outputDir, "results.csv").writeText(
            buildString {
                appendLine(
                    "case_id,text_length,submit_to_start_ms,first_packet_ms,synthesis_ms,audio_duration_ms,rtf," +
                        "submit_to_playback_complete_ms,previous_playback_complete_to_first_packet_ms," +
                        "cpu_min_before_khz,cpu_min_after_khz,cpu_max_before_khz,cpu_max_after_khz," +
                        "thermal_max_before_millic,thermal_max_after_millic,completed,errors,text",
                )
                results.forEach {
                    appendCsvLine(
                        it.caseId,
                        it.text.length.toString(),
                        it.submitToStartMs.toString(),
                        it.firstPacketMs.toString(),
                        it.synthesisMs.toString(),
                        it.audioDurationMs.toString(),
                        fmt(it.rtf),
                        it.submitToPlaybackCompleteMs.toString(),
                        it.previousPlaybackCompleteToFirstPacketMs.toString(),
                        it.cpuBefore.minCpuKHz.toString(),
                        it.cpuAfter.minCpuKHz.toString(),
                        it.cpuBefore.maxCpuKHz.toString(),
                        it.cpuAfter.maxCpuKHz.toString(),
                        it.cpuBefore.maxThermalMilliC.toString(),
                        it.cpuAfter.maxThermalMilliC.toString(),
                        it.completed.toString(),
                        it.errors.joinToString("; "),
                        it.text,
                    )
                }
            },
            Charsets.UTF_8,
        )
        val summary = buildSummary(createEngineMs, results)
        File(outputDir, "summary.json").writeText(summary.toString(2) + "\n", Charsets.UTF_8)
        File(outputDir, "TEST_REPORT_ZH.md").writeText(buildReport(summary), Charsets.UTF_8)
        Log.i(TAG, "artifacts outputDir=${outputDir.absolutePath}")
    }

    private fun buildSummary(createEngineMs: Long, results: List<SpeakResult>): JSONObject {
        val firstFive = results.take(5)
        val lastFive = results.takeLast(5)
        val rtfFirst = firstFive.mapNotNull { it.rtf.takeIf { value -> value >= 0.0 } }
        val rtfLast = lastFive.mapNotNull { it.rtf.takeIf { value -> value >= 0.0 } }
        val gaps = results.drop(1).map { it.previousPlaybackCompleteToFirstPacketMs }.filter { it >= 0L }
        return JSONObject()
            .put("runId", runId)
            .put("integrationPath", "aarHost implementation(files(\"../sdk/build/outputs/aar/sdk-release.aar\"))")
            .put("devicePackage", context.packageName)
            .put("language", LANGUAGE)
            .put("voiceId", VOICE_ID)
            .put("playType", PlayType.SYNTHESIZE_AND_PLAY.name)
            .put("queueMode", QueueMode.PREEMPT.name)
            .put("chunkSize", CHUNK_SIZE)
            .put("pcmQueueCapacity", PCM_QUEUE_CAPACITY)
            .put("createEngineMs", createEngineMs)
            .put("roundCount", ROUND_COUNT)
            .put("sentenceCount", SENTENCE_COUNT)
            .put("totalSpeaks", results.size)
            .put("passedSpeaks", results.count { it.completed && it.errors.isEmpty() })
            .put("failedSpeaks", results.count { !it.completed || it.errors.isNotEmpty() })
            .put("rtfAll", metricJsonDouble(results.mapNotNull { it.rtf.takeIf { value -> value >= 0.0 } }.sorted()))
            .put("rtfFirstFiveAvg", rtfFirst.averageOrNull())
            .put("rtfLastFiveAvg", rtfLast.averageOrNull())
            .put("rtfLastVsFirstRatio", if (rtfFirst.isNotEmpty() && rtfLast.isNotEmpty()) rtfLast.average() / rtfFirst.average() else JSONObject.NULL)
            .put("firstPacketMs", metricJson(results.map { it.firstPacketMs }.filter { it >= 0L }.sorted()))
            .put("audibleGapMs", metricJson(gaps.sorted()))
            .put("submitToPlaybackCompleteMs", metricJson(results.map { it.submitToPlaybackCompleteMs }.filter { it >= 0L }.sorted()))
            .put("minCpuBeforeKHz", metricJson(results.map { it.cpuBefore.minCpuKHz }.filter { it >= 0L }.sorted()))
            .put("minCpuAfterKHz", metricJson(results.map { it.cpuAfter.minCpuKHz }.filter { it >= 0L }.sorted()))
            .put("maxThermalBeforeMilliC", metricJson(results.map { it.cpuBefore.maxThermalMilliC }.filter { it >= 0L }.sorted()))
            .put("maxThermalAfterMilliC", metricJson(results.map { it.cpuAfter.maxThermalMilliC }.filter { it >= 0L }.sorted()))
            .put("results", JSONArray(results.map { it.toJson() }))
    }

    private fun buildReport(summary: JSONObject): String {
        val rtf = summary.getJSONObject("rtfAll")
        val firstPacket = summary.getJSONObject("firstPacketMs")
        val gap = summary.getJSONObject("audibleGapMs")
        val rtfRatio = summary.optDouble("rtfLastVsFirstRatio", Double.NaN)
        return buildString {
            appendLine("# Android AAR 多句多轮 speak 热稳定与听感时延测试")
            appendLine()
            appendLine("- AAR: `sdk-release.aar`")
            appendLine("- 总调用: `${summary.getInt("totalSpeaks")}` 次 `SYNTHESIZE_AND_PLAY`")
            appendLine("- 通过: `${summary.getInt("passedSpeaks")}/${summary.getInt("totalSpeaks")}`")
            appendLine("- RTF: avg `${fmt(rtf.optDouble("avg"))}`, P50 `${rtf.opt("p50")}`, P90 `${rtf.opt("p90")}`, max `${rtf.opt("max")}`")
            appendLine("- 前 5 次平均 RTF: `${fmt(summary.optDouble("rtfFirstFiveAvg"))}`")
            appendLine("- 后 5 次平均 RTF: `${fmt(summary.optDouble("rtfLastFiveAvg"))}`")
            appendLine("- 后 5 / 前 5 RTF 比值: `${fmt(rtfRatio)}`")
            appendLine("- 首包时延: P50 `${firstPacket.opt("p50")} ms`, P90 `${firstPacket.opt("p90")} ms`, max `${firstPacket.opt("max")} ms`")
            appendLine("- 上一句播放完成到下一句首包: P50 `${gap.opt("p50")} ms`, P90 `${gap.opt("p90")} ms`, max `${gap.opt("max")} ms`")
            appendLine()
            appendLine("原始数据见 `results.csv`，完整摘要见 `summary.json`。")
        }
    }

    private fun metricJson(values: List<Long>): JSONObject =
        JSONObject()
            .put("count", values.size)
            .put("min", values.firstOrNull() ?: JSONObject.NULL)
            .put("p50", percentile(values, 0.50))
            .put("p90", percentile(values, 0.90))
            .put("p95", percentile(values, 0.95))
            .put("max", values.lastOrNull() ?: JSONObject.NULL)
            .put("avg", if (values.isNotEmpty()) values.average() else JSONObject.NULL)

    private fun metricJsonDouble(values: List<Double>): JSONObject =
        JSONObject()
            .put("count", values.size)
            .put("min", values.firstOrNull() ?: JSONObject.NULL)
            .put("p50", percentileDouble(values, 0.50))
            .put("p90", percentileDouble(values, 0.90))
            .put("p95", percentileDouble(values, 0.95))
            .put("max", values.lastOrNull() ?: JSONObject.NULL)
            .put("avg", if (values.isNotEmpty()) values.average() else JSONObject.NULL)

    private fun percentile(values: List<Long>, p: Double): Any {
        if (values.isEmpty()) return JSONObject.NULL
        return values[((values.size - 1) * p).toInt().coerceIn(values.indices)]
    }

    private fun percentileDouble(values: List<Double>, p: Double): Any {
        if (values.isEmpty()) return JSONObject.NULL
        return values[((values.size - 1) * p).toInt().coerceIn(values.indices)]
    }

    private fun List<Double>.averageOrNull(): Any = if (isNotEmpty()) average() else JSONObject.NULL

    private fun StringBuilder.appendCsvLine(vararg cells: String) {
        append(cells.joinToString(",") { it.csvEscape() })
        append('\n')
    }

    private fun String.csvEscape(): String = "\"" + replace("\"", "\"\"") + "\""

    private fun fmt(value: Double): String =
        if (value.isNaN() || value.isInfinite()) "--" else String.format(Locale.US, "%.4f", value)

    private fun buildSamples(): List<String> = listOf(
        "今天天气很好适合出门散步听音乐放松一下。",
        "电量剩余百分之六十八，请及时连接充电器。",
        "请稍等片刻，系统正在准备新的语音播报内容。",
        "Room 204 is ready，请通知下一位用户进入房间。",
        "股票上涨二点一八个百分点，成交量继续放大。",
        "导航将在前方五百米右转，然后进入主路。",
    )

    private data class SpeakResult(
        val caseId: String,
        val text: String,
        val submitAtMs: Long,
        val submitToStartMs: Long,
        val firstPacketMs: Long,
        val synthesisMs: Long,
        val audioDurationMs: Long,
        val rtf: Double,
        val submitToPlaybackCompleteMs: Long,
        val previousPlaybackCompleteToFirstPacketMs: Long,
        val playbackCompleteAtMs: Long,
        val completed: Boolean,
        val cpuBefore: DeviceSnapshot,
        val cpuAfter: DeviceSnapshot,
        val errors: List<String>,
    ) {
        fun toJson(): JSONObject = JSONObject()
            .put("caseId", caseId)
            .put("text", text)
            .put("submitAtMs", submitAtMs)
            .put("submitToStartMs", submitToStartMs)
            .put("firstPacketMs", firstPacketMs)
            .put("synthesisMs", synthesisMs)
            .put("audioDurationMs", audioDurationMs)
            .put("rtf", rtf)
            .put("submitToPlaybackCompleteMs", submitToPlaybackCompleteMs)
            .put("previousPlaybackCompleteToFirstPacketMs", previousPlaybackCompleteToFirstPacketMs)
            .put("playbackCompleteAtMs", playbackCompleteAtMs)
            .put("completed", completed)
            .put("cpuBefore", cpuBefore.toJson())
            .put("cpuAfter", cpuAfter.toJson())
            .put("errors", JSONArray(errors))

        fun toLogLine(): String =
            "case=$caseId firstPacketMs=$firstPacketMs rtf=$rtf " +
                "audibleGapMs=$previousPlaybackCompleteToFirstPacketMs " +
                "cpuMinBefore=${cpuBefore.minCpuKHz} cpuMinAfter=${cpuAfter.minCpuKHz} " +
                "thermalBefore=${cpuBefore.maxThermalMilliC} thermalAfter=${cpuAfter.maxThermalMilliC} errors=$errors"
    }

    private class SingleSpeakListener(private val caseId: String) : SpeakListener {
        val playbackCompleteLatch = CountDownLatch(1)
        val errors = mutableListOf<String>()
        @Volatile var startAtMs: Long = -1L
        @Volatile var firstPacketMs: Long = -1L
        @Volatile var synthesisMs: Long = -1L
        @Volatile var audioDurationMs: Long = -1L
        @Volatile var rtf: Double = -1.0
        @Volatile var playbackCompleteAtMs: Long = -1L

        override fun onStart(requestId: String, response: StartResponse) {
            startAtMs = SystemClock.elapsedRealtime()
        }

        override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) = Unit

        override fun onComplete(requestId: String, response: CompleteResponse) {
            if (response.type == CompleteType.SYNTHESIS_COMPLETE) {
                firstPacketMs = response.firstPacketMs
                synthesisMs = response.synthesisMs
                audioDurationMs = response.audioDurationMs
                rtf = response.rtf
            } else if (response.type == CompleteType.PLAYBACK_COMPLETE) {
                playbackCompleteAtMs = SystemClock.elapsedRealtime()
                playbackCompleteLatch.countDown()
            }
        }

        override fun onStop(requestId: String, response: StopResponse) = Unit

        override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
            errors += "$caseId:$requestId:$errorCode:$errorMessage"
            playbackCompleteLatch.countDown()
        }
    }

    private data class DeviceSnapshot(
        val cpuKHzByCore: List<Long>,
        val thermalMilliCByZone: List<Long>,
    ) {
        val minCpuKHz: Long = cpuKHzByCore.filter { it >= 0L }.minOrNull() ?: -1L
        val maxCpuKHz: Long = cpuKHzByCore.filter { it >= 0L }.maxOrNull() ?: -1L
        val maxThermalMilliC: Long = thermalMilliCByZone.filter { it >= 0L }.maxOrNull() ?: -1L

        fun toJson(): JSONObject = JSONObject()
            .put("cpuKHzByCore", JSONArray(cpuKHzByCore))
            .put("thermalMilliCByZone", JSONArray(thermalMilliCByZone))
            .put("minCpuKHz", minCpuKHz)
            .put("maxCpuKHz", maxCpuKHz)
            .put("maxThermalMilliC", maxThermalMilliC)

        companion object {
            fun capture(): DeviceSnapshot =
                DeviceSnapshot(
                    cpuKHzByCore = (0 until 12).mapNotNull { index ->
                        val path = File("/sys/devices/system/cpu/cpu$index/cpufreq/scaling_cur_freq")
                        if (path.exists()) path.readLongOrNull() else null
                    },
                    thermalMilliCByZone = (0 until 32).mapNotNull { index ->
                        val path = File("/sys/class/thermal/thermal_zone$index/temp")
                        if (path.exists()) path.readLongOrNull() else null
                    },
                )
        }
    }

    companion object {
        private const val TAG = "AarMultiSpeakThermal"
        private const val LANGUAGE = "zh-en"
        private const val VOICE_ID = "lits-female-02"
        private const val TIMEOUT_MS = 90_000L
        private const val ROUND_COUNT = 4
        private const val SENTENCE_COUNT = 6
        private const val CHUNK_SIZE = 50
        private const val PCM_QUEUE_CAPACITY = 128
        private const val INTER_SPEAK_SLEEP_MS = 80L
    }
}

private fun File.readLongOrNull(): Long =
    runCatching { readText().trim().toLong() }.getOrDefault(-1L)
