package com.lits.tts.sdk.internal

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
import java.util.Collections
import java.util.Locale
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class StopThenSpeakLatency100Test {
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()
    private val outputDir = File(
        context.getExternalFilesDir(null) ?: context.filesDir,
        "stop-speak-latency-100",
    ).apply { mkdirs() }
    private val runId = "stop-speak-100-${System.currentTimeMillis()}"
    private val samples = buildSamples()

    @Test
    fun stopThenSpeakLatencyAcross100Samples() {
        assertEquals("sample count", 100, samples.size)
        TextToSpeechSdk.setWorkPath(File(context.cacheDir, "stop-speak-latency-work").apply {
            deleteRecursively()
            mkdirs()
        }.absolutePath)

        val engine = TextToSpeechSdk.createEngine(
            CreateEngineParams(
                language = LANGUAGE,
                mode = RunMode.OFFLINE,
                voiceId = VOICE_ID,
                engineName = runId,
            ),
        )

        val results = mutableListOf<TrialResult>()
        try {
            warmup(engine)
            samples.forEachIndexed { index, text ->
                val result = runTrial(engine, index + 1, text)
                results += result
                Log.i(TAG, result.toLogLine())
            }
        } finally {
            runCatching { engine.shutdown() }
        }

        writeArtifacts(results)
        assertTrue(
            "stop/speak failures: ${results.filter { !it.status.startsWith("PASS") }.map { it.caseId to it.message }}",
            results.all { it.status.startsWith("PASS") },
        )
    }

    private fun warmup(engine: TextToSpeechEngine) {
        val listener = TrialListener("warmup")
        engine.setListener(listener)
        val requestId = "warmup-$runId"
        engine.speak(
            "Warmup before the stop then speak latency test.",
            speakParams(requestId),
        )
        assertTrue("warmup synthesis complete timeout", listener.synthesisCompleteLatch.await(30, TimeUnit.SECONDS))
        engine.stop()
        listener.stopLatch.await(5, TimeUnit.SECONDS)
    }

    private fun runTrial(engine: TextToSpeechEngine, index: Int, text: String): TrialResult {
        val caseId = "case-${index.toString().padStart(3, '0')}"
        val firstRequestId = "$caseId-first-$runId"
        val secondRequestId = "$caseId-second-$runId"
        val listener = TrialListener(caseId)
        engine.setListener(listener)

        val firstSubmitAt = System.currentTimeMillis()
        engine.speak(text, speakParams(firstRequestId))
        Thread.sleep(STOP_AFTER_MS)
        val stopCalledAt = System.currentTimeMillis()
        engine.stop()
        val stopped = listener.stopLatch.await(STOP_TIMEOUT_MS, TimeUnit.MILLISECONDS)
        val onStopAt = listener.stopEvents.firstOrNull()?.atMs ?: -1L
        Thread.sleep(RESTART_AFTER_STOP_MS)

        listener.resetForSecondRequest()
        val secondSubmitAt = System.currentTimeMillis()
        engine.speak(text, speakParams(secondRequestId))
        val synthesisCompleteSeen = listener.synthesisCompleteLatch.await(SYNTHESIS_TIMEOUT_MS, TimeUnit.MILLISECONDS)
        val secondSynthesisCompleteAt = listener.synthesisCompleteAtMs
        val firstPacketMs = listener.secondCompleteFirstPacketMs
        engine.stop()
        listener.secondStopLatch.await(STOP_TIMEOUT_MS, TimeUnit.MILLISECONDS)

        val expectedFirstStopNoAudio = listener.errors.isNotEmpty() && listener.errors.all {
            it.requestId == firstRequestId &&
                it.code == 1002300011 &&
                it.message.contains("streaming playback produced no synthesized audio")
        }
        val hasUnexpectedErrors = listener.errors.any {
            !(it.requestId == firstRequestId &&
                it.code == 1002300011 &&
                it.message.contains("streaming playback produced no synthesized audio"))
        }
        val status = if (stopped && synthesisCompleteSeen && firstPacketMs >= 0L && !hasUnexpectedErrors) {
            if (expectedFirstStopNoAudio) "PASS_WITH_FIRST_STOP_NO_AUDIO" else "PASS"
        } else {
            "FAIL"
        }
        val message = when {
            hasUnexpectedErrors -> listener.errors.joinToString("; ") { "${it.requestId}:${it.code}:${it.message}" }
            expectedFirstStopNoAudio -> listener.errors.joinToString("; ") { "${it.requestId}:${it.code}:${it.message}" }
            !stopped -> "first request stop callback timed out"
            !synthesisCompleteSeen -> "second request synthesis complete timed out"
            firstPacketMs < 0L -> "second request did not report firstPacketMs"
            else -> ""
        }

        return TrialResult(
            caseId = caseId,
            status = status,
            text = text,
            firstRequestId = firstRequestId,
            secondRequestId = secondRequestId,
            firstSubmitAtMs = firstSubmitAt,
            stopCalledAtMs = stopCalledAt,
            firstOnStopAtMs = onStopAt,
            secondSubmitAtMs = secondSubmitAt,
            secondSynthesisCompleteAtMs = secondSynthesisCompleteAt,
            secondFirstPacketMs = firstPacketMs,
            stopCallbackMs = if (onStopAt > 0L) onStopAt - stopCalledAt else -1L,
            stopToSecondSubmitMs = secondSubmitAt - (if (onStopAt > 0L) onStopAt else stopCalledAt),
            stopToSecondFirstPacketMs = if (onStopAt > 0L && firstPacketMs >= 0L) {
                secondSubmitAt + firstPacketMs - onStopAt
            } else {
                -1L
            },
            secondStartLatencyMs = listener.secondStartAtMs.takeIf { it > 0L }?.let { it - secondSubmitAt } ?: -1L,
            secondSynthesisMs = listener.secondCompleteSynthesisMs,
            secondAudioDurationMs = listener.secondCompleteAudioDurationMs,
            secondRtf = listener.secondCompleteRtf,
            secondProfile = listener.secondCompleteProfile,
            message = message,
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

    private fun writeArtifacts(results: List<TrialResult>) {
        val samplesFile = File(outputDir, "samples.csv")
        samplesFile.writeText(
            buildString {
                appendLine("case_id,text_length,text")
                results.forEach {
                    appendCsvLine(it.caseId, it.text.length.toString(), it.text)
                }
            },
            Charsets.UTF_8,
        )

        val resultsFile = File(outputDir, "results.csv")
        resultsFile.writeText(
            buildString {
                appendLine(
                    "case_id,status,text_length,second_first_packet_ms,stop_callback_ms," +
                        "stop_to_second_submit_ms,stop_to_second_first_packet_ms,second_start_latency_ms," +
                        "second_synthesis_ms,second_audio_duration_ms,second_rtf,message,text",
                )
                results.forEach {
                    appendCsvLine(
                        it.caseId,
                        it.status,
                        it.text.length.toString(),
                        it.secondFirstPacketMs.toString(),
                        it.stopCallbackMs.toString(),
                        it.stopToSecondSubmitMs.toString(),
                        it.stopToSecondFirstPacketMs.toString(),
                        it.secondStartLatencyMs.toString(),
                        it.secondSynthesisMs.toString(),
                        it.secondAudioDurationMs.toString(),
                        it.secondRtf.toString(),
                        it.message,
                        it.text,
                    )
                }
            },
            Charsets.UTF_8,
        )

        val summary = buildSummary(results)
        File(outputDir, "summary.json").writeText(summary.toString(2) + "\n", Charsets.UTF_8)
        File(outputDir, "report.md").writeText(buildMarkdownReport(results, summary), Charsets.UTF_8)
        Log.i(TAG, "artifacts outputDir=${outputDir.absolutePath}")
    }

    private fun buildSummary(results: List<TrialResult>): JSONObject {
        val passed = results.filter { it.status.startsWith("PASS") }
        val firstStopNoAudio = results.filter { it.status == "PASS_WITH_FIRST_STOP_NO_AUDIO" }
        val firstPacketValues = passed.map { it.secondFirstPacketMs }.filter { it >= 0L }.sorted()
        val stopToPacketValues = passed.map { it.stopToSecondFirstPacketMs }.filter { it >= 0L }.sorted()
        val stopCallbackValues = passed.map { it.stopCallbackMs }.filter { it >= 0L }.sorted()
        return JSONObject()
            .put("runId", runId)
            .put("devicePackage", context.packageName)
            .put("language", LANGUAGE)
            .put("voiceId", VOICE_ID)
            .put("playType", PlayType.SYNTHESIZE_AND_PLAY.name)
            .put("queueMode", QueueMode.PREEMPT.name)
            .put("chunkSize", CHUNK_SIZE)
            .put("pcmQueueCapacity", PCM_QUEUE_CAPACITY)
            .put("stopAfterMs", STOP_AFTER_MS)
            .put("restartAfterStopMs", RESTART_AFTER_STOP_MS)
            .put("total", results.size)
            .put("passed", passed.size)
            .put("failed", results.size - passed.size)
            .put("firstStopNoAudio", firstStopNoAudio.size)
            .put("secondFirstPacketMs", metricJson(firstPacketValues))
            .put("stopToSecondFirstPacketMs", metricJson(stopToPacketValues))
            .put("stopCallbackMs", metricJson(stopCallbackValues))
            .put("failures", JSONArray(results.filter { it.status != "PASS" }.map { it.toJson() }))
            .put("artifactsDir", outputDir.absolutePath)
    }

    private fun metricJson(values: List<Long>): JSONObject =
        JSONObject()
            .put("count", values.size)
            .put("min", values.firstOrNull() ?: JSONObject.NULL)
            .put("p50", percentile(values, 0.50))
            .put("p90", percentile(values, 0.90))
            .put("p95", percentile(values, 0.95))
            .put("p99", percentile(values, 0.99))
            .put("max", values.lastOrNull() ?: JSONObject.NULL)
            .put("avg", if (values.isNotEmpty()) values.average() else JSONObject.NULL)

    private fun percentile(values: List<Long>, p: Double): Any {
        if (values.isEmpty()) return JSONObject.NULL
        val index = ((values.size - 1) * p).toInt().coerceIn(values.indices)
        return values[index]
    }

    private fun buildMarkdownReport(results: List<TrialResult>, summary: JSONObject): String =
        buildString {
            appendLine("# Stop-Then-Speak Latency 100-Sample Report")
            appendLine()
            appendLine("- Run ID: `$runId`")
            appendLine("- Samples: `${results.size}`")
            appendLine("- Passed: `${summary.getInt("passed")}`")
            appendLine("- Failed: `${summary.getInt("failed")}`")
            appendLine("- Mode: `$LANGUAGE`, voice `$VOICE_ID`, `SYNTHESIZE_AND_PLAY`, `PREEMPT`")
            appendLine("- Params: `chunkSize=$CHUNK_SIZE`, `pcmQueueCapacity=$PCM_QUEUE_CAPACITY`, `stopAfterMs=$STOP_AFTER_MS`, `restartAfterStopMs=$RESTART_AFTER_STOP_MS`")
            appendLine()
            appendLine("## Second Speak First Packet")
            appendLine()
            appendLine(summary.getJSONObject("secondFirstPacketMs").toPrettyMetric())
            appendLine()
            appendLine("## Stop Completion To Second First Packet")
            appendLine()
            appendLine(summary.getJSONObject("stopToSecondFirstPacketMs").toPrettyMetric())
        }

    private fun JSONObject.toPrettyMetric(): String =
        "count=${getInt("count")}, min=${opt("min")} ms, p50=${opt("p50")} ms, " +
            "p90=${opt("p90")} ms, p95=${opt("p95")} ms, p99=${opt("p99")} ms, " +
            "max=${opt("max")} ms, avg=${String.format(Locale.US, "%.1f", optDouble("avg"))} ms"

    private fun StringBuilder.appendCsvLine(vararg cells: String) {
        append(cells.joinToString(",") { it.csvEscape() })
        append('\n')
    }

    private fun String.csvEscape(): String = "\"" + replace("\"", "\"\"") + "\""

    private class TrialListener(private val caseId: String) : SpeakListener {
        @Volatile var synthesisCompleteLatch = CountDownLatch(1)
        @Volatile var secondStopLatch = CountDownLatch(1)
        val stopLatch = CountDownLatch(1)
        val stopEvents = Collections.synchronizedList(mutableListOf<StopEvent>())
        val errors = Collections.synchronizedList(mutableListOf<ErrorEvent>())
        @Volatile var synthesisCompleteAtMs: Long = -1L
        @Volatile var secondCompleteFirstPacketMs: Long = -1L
        @Volatile var secondCompleteSynthesisMs: Long = -1L
        @Volatile var secondCompleteAudioDurationMs: Long = -1L
        @Volatile var secondCompleteRtf: Double = -1.0
        @Volatile var secondCompleteProfile: String = ""
        @Volatile var secondStartAtMs: Long = -1L
        @Volatile private var measuringSecond = false

        fun resetForSecondRequest() {
            synthesisCompleteAtMs = -1L
            secondCompleteFirstPacketMs = -1L
            secondCompleteSynthesisMs = -1L
            secondCompleteAudioDurationMs = -1L
            secondCompleteRtf = -1.0
            secondCompleteProfile = ""
            synthesisCompleteLatch = CountDownLatch(1)
            secondStopLatch = CountDownLatch(1)
            measuringSecond = true
        }

        override fun onStart(requestId: String, response: StartResponse) {
            if (measuringSecond) {
                secondStartAtMs = System.currentTimeMillis()
            }
        }

        override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) {
        }

        override fun onComplete(requestId: String, response: CompleteResponse) {
            if (response.type == CompleteType.SYNTHESIS_COMPLETE) {
                synthesisCompleteAtMs = System.currentTimeMillis()
                if (measuringSecond) {
                    secondCompleteFirstPacketMs = response.firstPacketMs
                    secondCompleteSynthesisMs = response.synthesisMs
                    secondCompleteAudioDurationMs = response.audioDurationMs
                    secondCompleteRtf = response.rtf
                    secondCompleteProfile = response.profilingInfo
                }
                synthesisCompleteLatch.countDown()
            } else if (response.type == CompleteType.PLAYBACK_COMPLETE && measuringSecond) {
                secondStopLatch.countDown()
            }
        }

        override fun onStop(requestId: String, response: StopResponse) {
            stopEvents += StopEvent(requestId, System.currentTimeMillis())
            if (measuringSecond) {
                secondStopLatch.countDown()
            } else {
                stopLatch.countDown()
            }
        }

        override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
            errors += ErrorEvent(requestId, errorCode, errorMessage)
            synthesisCompleteLatch.countDown()
            stopLatch.countDown()
            secondStopLatch.countDown()
            Log.e(TAG, "case=$caseId requestId=$requestId error=$errorCode message=$errorMessage")
        }
    }

    private data class StopEvent(val requestId: String, val atMs: Long)
    private data class ErrorEvent(val requestId: String, val code: Int, val message: String)

    private data class TrialResult(
        val caseId: String,
        val status: String,
        val text: String,
        val firstRequestId: String,
        val secondRequestId: String,
        val firstSubmitAtMs: Long,
        val stopCalledAtMs: Long,
        val firstOnStopAtMs: Long,
        val secondSubmitAtMs: Long,
        val secondSynthesisCompleteAtMs: Long,
        val secondFirstPacketMs: Long,
        val stopCallbackMs: Long,
        val stopToSecondSubmitMs: Long,
        val stopToSecondFirstPacketMs: Long,
        val secondStartLatencyMs: Long,
        val secondSynthesisMs: Long,
        val secondAudioDurationMs: Long,
        val secondRtf: Double,
        val secondProfile: String,
        val message: String,
    ) {
        fun toJson(): JSONObject = JSONObject()
            .put("caseId", caseId)
            .put("status", status)
            .put("text", text)
            .put("firstRequestId", firstRequestId)
            .put("secondRequestId", secondRequestId)
            .put("secondFirstPacketMs", secondFirstPacketMs)
            .put("stopCallbackMs", stopCallbackMs)
            .put("stopToSecondSubmitMs", stopToSecondSubmitMs)
            .put("stopToSecondFirstPacketMs", stopToSecondFirstPacketMs)
            .put("secondSynthesisMs", secondSynthesisMs)
            .put("secondAudioDurationMs", secondAudioDurationMs)
            .put("secondRtf", secondRtf)
            .put("message", message)

        fun toLogLine(): String =
            "case=$caseId status=$status secondFirstPacketMs=$secondFirstPacketMs " +
                "stopCallbackMs=$stopCallbackMs stopToSecondFirstPacketMs=$stopToSecondFirstPacketMs " +
                "synthesisMs=$secondSynthesisMs audioDurationMs=$secondAudioDurationMs rtf=$secondRtf message=$message"
    }

    private fun buildSamples(): List<String> {
        val brands = listOf(
            "OpenAI", "DeepSeek", "Qwen", "Doubao", "Kimi", "Sora", "Grok", "Mistral",
            "Midjourney", "MiniMax", "Moonshot", "Baidu", "Quark", "Alipay", "Taobao",
            "Tmall", "Pinduoduo", "Meituan", "Eleme", "Didi", "Ctrip", "Douyin", "TikTok",
            "Kuaishou", "Bilibili", "Xiaohongshu", "Weibo", "Zhihu", "Youku", "iQIYI",
            "WeChat", "WhatsApp", "Instagram", "Xiaomi", "Huawei", "HONOR", "OnePlus",
            "Redmi", "realme", "Meizu", "Nubia", "DJI", "BYD", "NIO", "XPeng", "AITO",
            "Zeekr", "Geely", "Chery", "CATL",
        )
        val systems = listOf("HarmonyOS", "HarmonyOS NEXT", "HyperOS", "MagicOS", "ColorOS", "OriginOS", "Flyme", "EMUI")
        val domains = listOf(
            "www.baidu.com", "baidu.com", "openai.com", "chatgpt.com", "deepseek.com",
            "bilibili.com", "taobao.com", "jd.com", "douyin.com", "xiaohongshu.com",
            "weibo.com", "zhihu.com",
        )
        val actions = listOf(
            "open the assistant and read the message",
            "check account status and continue playback",
            "prepare a navigation reminder for the driver",
            "summarize the notification and keep speaking",
            "verify the device setting after restart",
            "read the delivery note with stable streaming",
            "switch the service card and report progress",
            "confirm the cloud request and local response",
        )
        return (0 until 100).map { index ->
            val a = brands[index % brands.size]
            val b = brands[(index * 7 + 3) % brands.size]
            val system = systems[index % systems.size]
            val domain = domains[index % domains.size]
            val action = actions[index % actions.size]
            val number = (index + 1).toString().padStart(3, '0')
            "Sample $number asks $a and $b on $system to $action through $domain while the user stops playback and speaks again for latency testing."
        }
    }

    companion object {
        private const val TAG = "StopSpeak100"
        private const val LANGUAGE = "zh-en"
        private const val VOICE_ID = "lits-female-02"
        private const val CHUNK_SIZE = 50
        private const val PCM_QUEUE_CAPACITY = 32
        private const val STOP_AFTER_MS = 300L
        private const val RESTART_AFTER_STOP_MS = 300L
        private const val STOP_TIMEOUT_MS = 5_000L
        private const val SYNTHESIS_TIMEOUT_MS = 30_000L
    }
}
