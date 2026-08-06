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

class AarInterfaceLongTextFirstPacketRtfStep4Test {
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()
    private val outputDir = File(
        context.getExternalFilesDir(null) ?: context.filesDir,
        "aar-long-text-first-packet-rtf-step4",
    ).apply { mkdirs() }
    private val runId = "aar-long-text-step4-${System.currentTimeMillis()}"

    @Test
    fun batchLongTextsReportFirstPacketAndRtfWithStep4Aar() {
        val samples = buildSamples()
        assertEquals("sample count", SAMPLE_COUNT, samples.size)
        samples.forEach { sample ->
            assertTrue("${sample.caseId} must exceed 100 chars", sample.text.length > 100)
        }

        TextToSpeechSdk.setWorkPath(File(context.cacheDir, "aar-long-text-step4-work").apply {
            deleteRecursively()
            mkdirs()
        }.absolutePath)

        val createEngineStartMs = SystemClock.elapsedRealtime()
        val engine = TextToSpeechSdk.createEngine(
            CreateEngineParams(
                language = LANGUAGE,
                mode = RunMode.OFFLINE,
                voiceId = VOICE_ID,
                engineName = runId,
            ),
        )
        val createEngineMs = SystemClock.elapsedRealtime() - createEngineStartMs

        val results = mutableListOf<SpeakResult>()
        try {
            runWarmup(engine)
            samples.forEach { sample ->
                val result = runSpeak(engine, sample)
                results += result
                Log.i(TAG, result.toLogLine())
                Thread.sleep(INTER_SPEAK_SLEEP_MS)
            }
        } finally {
            runCatching { engine.shutdown() }
        }

        writeArtifacts(createEngineMs, results)
        assertEquals("speak count", SAMPLE_COUNT, results.size)
        assertTrue("unexpected errors: ${results.flatMap { it.errors }}", results.all { it.errors.isEmpty() })
        assertTrue("missing first packet", results.all { it.firstPacketMs >= 0L })
        assertTrue("missing rtf", results.all { it.rtf >= 0.0 })
        assertTrue(
            "effective chunk mismatch: ${results.map { it.effectiveStreamingChunkSize }}",
            results.all { it.effectiveStreamingChunkSize == CHUNK_SIZE },
        )
    }

    private fun runWarmup(engine: TextToSpeechEngine) {
        val listener = SingleSpeakListener("warmup")
        engine.setListener(listener)
        engine.speak("这是安卓三点零四步解码AAR长文本批测的预热句。", speakParams("warmup-$runId"))
        assertTrue("warmup synthesis timeout", listener.synthesisCompleteLatch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS))
    }

    private fun runSpeak(engine: TextToSpeechEngine, sample: TextSample): SpeakResult {
        val listener = SingleSpeakListener(sample.caseId)
        engine.setListener(listener)
        val submitAtMs = SystemClock.elapsedRealtime()
        engine.speak(sample.text, speakParams("${sample.caseId}-$runId"))
        val completed = listener.synthesisCompleteLatch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS)
        val completeAtMs = listener.synthesisCompleteAtMs
        return SpeakResult(
            caseId = sample.caseId,
            text = sample.text,
            textLength = sample.text.length,
            submitAtMs = submitAtMs,
            submitToStartMs = listener.startAtMs - submitAtMs,
            submitToSynthesisCompleteMs = if (completeAtMs >= 0L) completeAtMs - submitAtMs else -1L,
            firstPacketMs = listener.firstPacketMs,
            synthesisMs = listener.synthesisMs,
            audioDurationMs = listener.audioDurationMs,
            rtf = listener.rtf,
            profilingInfo = listener.profilingInfo,
            effectiveStreamingChunkSize = listener.effectiveStreamingChunkSize,
            effectivePcmQueueCapacity = listener.effectivePcmQueueCapacity,
            completed = completed,
            errors = listener.errors.toList(),
        )
    }

    private fun speakParams(requestId: String): SpeakParams =
        SpeakParams(
            requestId = requestId,
            speed = 1.0f,
            playType = PlayType.SYNTHESIZE_ONLY,
            queueMode = QueueMode.PREEMPT,
            languageContext = LANGUAGE,
            streamingConfig = TtsStreamingConfig(
                chunkSize = CHUNK_SIZE,
                firstChunkSize = CHUNK_SIZE,
                pcmQueueCapacity = PCM_QUEUE_CAPACITY,
            ),
        )

    private fun writeArtifacts(createEngineMs: Long, results: List<SpeakResult>) {
        File(outputDir, "results.csv").writeText(buildCsv(results), Charsets.UTF_8)
        val summary = buildSummary(createEngineMs, results)
        File(outputDir, "summary.json").writeText(summary.toString(2) + "\n", Charsets.UTF_8)
        File(outputDir, "TEST_REPORT_ZH.md").writeText(buildReport(summary), Charsets.UTF_8)
        Log.i(TAG, "artifacts outputDir=${outputDir.absolutePath}")
    }

    private fun buildCsv(results: List<SpeakResult>): String = buildString {
        appendLine(
            "case_id,text_length,submit_to_start_ms,first_packet_ms,synthesis_ms,audio_duration_ms,rtf," +
                "submit_to_synthesis_complete_ms,effective_chunk_size,effective_pcm_queue_capacity,profiling_info,errors,text",
        )
        results.forEach {
            appendCsvLine(
                it.caseId,
                it.textLength.toString(),
                it.submitToStartMs.toString(),
                it.firstPacketMs.toString(),
                it.synthesisMs.toString(),
                it.audioDurationMs.toString(),
                fmt(it.rtf),
                it.submitToSynthesisCompleteMs.toString(),
                it.effectiveStreamingChunkSize.toString(),
                it.effectivePcmQueueCapacity.toString(),
                it.profilingInfo,
                it.errors.joinToString("; "),
                it.text,
            )
        }
    }

    private fun buildSummary(createEngineMs: Long, results: List<SpeakResult>): JSONObject =
        JSONObject()
            .put("runId", runId)
            .put("integrationPath", "aarHost implementation(files(\"../sdk/build/outputs/aar/sdk-release.aar\"))")
            .put("devicePackage", context.packageName)
            .put("sdkVersion", "3.0")
            .put("decoderSteps", 4)
            .put("language", LANGUAGE)
            .put("voiceId", VOICE_ID)
            .put("playType", PlayType.SYNTHESIZE_ONLY.name)
            .put("queueMode", QueueMode.PREEMPT.name)
            .put("chunkSize", CHUNK_SIZE)
            .put("pcmQueueCapacity", PCM_QUEUE_CAPACITY)
            .put("createEngineMs", createEngineMs)
            .put("totalSpeaks", results.size)
            .put("passedSpeaks", results.count { it.completed && it.errors.isEmpty() })
            .put("failedSpeaks", results.count { !it.completed || it.errors.isNotEmpty() })
            .put("textLength", metricJson(results.map { it.textLength.toLong() }.sorted()))
            .put("firstPacketMs", metricJson(results.map { it.firstPacketMs }.filter { it >= 0L }.sorted()))
            .put("synthesisMs", metricJson(results.map { it.synthesisMs }.filter { it >= 0L }.sorted()))
            .put("audioDurationMs", metricJson(results.map { it.audioDurationMs }.filter { it >= 0L }.sorted()))
            .put("rtf", metricJsonDouble(results.map { it.rtf }.filter { it >= 0.0 }.sorted()))
            .put("submitToSynthesisCompleteMs", metricJson(results.map { it.submitToSynthesisCompleteMs }.filter { it >= 0L }.sorted()))
            .put("results", JSONArray(results.map { it.toJson() }))

    private fun buildReport(summary: JSONObject): String {
        val firstPacket = summary.getJSONObject("firstPacketMs")
        val rtf = summary.getJSONObject("rtf")
        val synthesis = summary.getJSONObject("synthesisMs")
        val textLength = summary.getJSONObject("textLength")
        return buildString {
            appendLine("# Android v3.0 step=4 AAR 长文本首包与 RTF 批测")
            appendLine()
            appendLine("- AAR: `sdk-release.aar`")
            appendLine("- decoder steps: `${summary.getInt("decoderSteps")}`")
            appendLine("- 输入: `${summary.getInt("totalSpeaks")}` 条中文长文本，长度 min `${textLength.opt("min")}`，P50 `${textLength.opt("p50")}`，max `${textLength.opt("max")}`")
            appendLine("- 播放模式: `${summary.getString("playType")}`，chunk `${summary.getInt("chunkSize")}`，PCM queue `${summary.getInt("pcmQueueCapacity")}`")
            appendLine("- 通过: `${summary.getInt("passedSpeaks")}/${summary.getInt("totalSpeaks")}`")
            appendLine("- 首包时延: avg `${fmt(firstPacket.optDouble("avg"))} ms`, P50 `${firstPacket.opt("p50")} ms`, P90 `${firstPacket.opt("p90")} ms`, P95 `${firstPacket.opt("p95")} ms`, max `${firstPacket.opt("max")} ms`")
            appendLine("- RTF: avg `${fmt(rtf.optDouble("avg"))}`, P50 `${rtf.opt("p50")}`, P90 `${rtf.opt("p90")}`, P95 `${rtf.opt("p95")}`, max `${rtf.opt("max")}`")
            appendLine("- synthesisMs: avg `${fmt(synthesis.optDouble("avg"))} ms`, P50 `${synthesis.opt("p50")} ms`, max `${synthesis.opt("max")} ms`")
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

    private fun StringBuilder.appendCsvLine(vararg cells: String) {
        append(cells.joinToString(",") { it.csvEscape() })
        append('\n')
    }

    private fun String.csvEscape(): String = "\"" + replace("\"", "\"\"") + "\""

    private fun fmt(value: Double): String =
        if (value.isNaN() || value.isInfinite()) "--" else String.format(Locale.US, "%.4f", value)

    private data class TextSample(val caseId: String, val text: String)

    private data class SpeakResult(
        val caseId: String,
        val text: String,
        val textLength: Int,
        val submitAtMs: Long,
        val submitToStartMs: Long,
        val submitToSynthesisCompleteMs: Long,
        val firstPacketMs: Long,
        val synthesisMs: Long,
        val audioDurationMs: Long,
        val rtf: Double,
        val profilingInfo: String,
        val effectiveStreamingChunkSize: Int,
        val effectivePcmQueueCapacity: Int,
        val completed: Boolean,
        val errors: List<String>,
    ) {
        fun toJson(): JSONObject = JSONObject()
            .put("caseId", caseId)
            .put("text", text)
            .put("textLength", textLength)
            .put("submitAtMs", submitAtMs)
            .put("submitToStartMs", submitToStartMs)
            .put("submitToSynthesisCompleteMs", submitToSynthesisCompleteMs)
            .put("firstPacketMs", firstPacketMs)
            .put("synthesisMs", synthesisMs)
            .put("audioDurationMs", audioDurationMs)
            .put("rtf", rtf)
            .put("profilingInfo", profilingInfo)
            .put("effectiveStreamingChunkSize", effectiveStreamingChunkSize)
            .put("effectivePcmQueueCapacity", effectivePcmQueueCapacity)
            .put("completed", completed)
            .put("errors", JSONArray(errors))

        fun toLogLine(): String =
            "case=$caseId textLength=$textLength firstPacketMs=$firstPacketMs rtf=$rtf " +
                "synthesisMs=$synthesisMs audioDurationMs=$audioDurationMs profile=$profilingInfo errors=$errors"
    }

    private class SingleSpeakListener(private val caseId: String) : SpeakListener {
        val synthesisCompleteLatch = CountDownLatch(1)
        val errors = mutableListOf<String>()
        @Volatile var startAtMs: Long = -1L
        @Volatile var synthesisCompleteAtMs: Long = -1L
        @Volatile var firstPacketMs: Long = -1L
        @Volatile var synthesisMs: Long = -1L
        @Volatile var audioDurationMs: Long = -1L
        @Volatile var rtf: Double = -1.0
        @Volatile var profilingInfo: String = ""
        @Volatile var effectiveStreamingChunkSize: Int = -1
        @Volatile var effectivePcmQueueCapacity: Int = -1

        override fun onStart(requestId: String, response: StartResponse) {
            startAtMs = SystemClock.elapsedRealtime()
            effectiveStreamingChunkSize = response.streamingChunkSize
            effectivePcmQueueCapacity = response.pcmQueueCapacity
        }

        override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) = Unit

        override fun onComplete(requestId: String, response: CompleteResponse) {
            if (response.type == CompleteType.SYNTHESIS_COMPLETE) {
                firstPacketMs = response.firstPacketMs
                synthesisMs = response.synthesisMs
                audioDurationMs = response.audioDurationMs
                rtf = response.rtf
                profilingInfo = response.profilingInfo
                synthesisCompleteAtMs = SystemClock.elapsedRealtime()
                synthesisCompleteLatch.countDown()
            }
        }

        override fun onStop(requestId: String, response: StopResponse) = Unit

        override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
            errors += "$caseId:$requestId:$errorCode:$errorMessage"
            synthesisCompleteLatch.countDown()
        }
    }

    companion object {
        private const val TAG = "AarLongStep4Rtf"
        private const val LANGUAGE = "zh-en"
        private const val VOICE_ID = "lits-female-02"
        private const val TIMEOUT_MS = 180_000L
        private const val SAMPLE_COUNT = 10
        private const val CHUNK_SIZE = 50
        private const val PCM_QUEUE_CAPACITY = 128
        private const val INTER_SPEAK_SLEEP_MS = 100L
        private const val LENGTH_SUFFIX =
            "另外为了避免短句统计口径带来的偏差，这条测试文本会继续补充设备状态、用户场景和后台任务说明，确保每个样例都稳定超过一百个字符。"

        private fun buildSamples(): List<TextSample> = listOf(
            TextSample("long-001", "今天的系统通知会连续播报多个模块的状态，包括网络连接、日程提醒、导航路线和后台任务进度。为了确认长文本合成的首包时延，我们保留超过一百字的输入长度，并让句子结构接近日常语音助手的真实播报场景。" + LENGTH_SUFFIX),
            TextSample("long-002", "会议将在十分钟后开始，请提前打开文档并检查麦克风权限。系统还会同步提醒参会人当前会议室的网络状态、投屏设备连接情况以及后续议程安排，用来覆盖较长中文文本在安卓端的稳定推理表现。" + LENGTH_SUFFIX),
            TextSample("long-003", "导航提示显示前方道路出现临时施工，建议保持当前车道继续行驶八百米后右转。应用会根据实时交通情况重新规划路线，同时播报预计到达时间、剩余里程和服务区信息，确保测试文本长度超过一百字。" + LENGTH_SUFFIX),
            TextSample("long-004", "智能家居场景中，客厅空调已经调整到二十六度，卧室灯光将在晚上十点自动切换到柔和模式。系统还检测到空气质量轻微下降，建议打开新风设备十分钟，并记录本次长文本播报的首包和实时率。" + LENGTH_SUFFIX),
            TextSample("long-005", "订单状态已经更新，第一件商品完成出库，第二件商品正在等待快递揽收。由于收货地址包含园区门牌、楼栋编号和联系电话，语音播报需要覆盖数字、普通中文和较长短语组合，方便观察四步解码的端侧性能。" + LENGTH_SUFFIX),
            TextSample("long-006", "今天的训练计划包含三十分钟慢跑、十五分钟力量练习和十分钟拉伸放松。健康助手会结合过去七天的睡眠记录、心率区间和运动恢复情况生成建议，因此这条文本保持较长长度来模拟真实健康播报。" + LENGTH_SUFFIX),
            TextSample("long-007", "后台下载任务已经完成百分之七十二，预计还需要两分钟结束。系统会继续监控电池温度、剩余存储空间和网络速度，如果检测到异常会立即提醒用户暂停任务，这段文本用于批量评估长文本首包时延。" + LENGTH_SUFFIX),
            TextSample("long-008", "新的日程摘要包括上午的产品评审、下午的客户沟通和晚上的版本回归测试。语音助手需要一次性播报多个事项，并在每个事项之间保持自然停顿，所以我们使用超过一百字的句子来测试合成链路。" + LENGTH_SUFFIX),
            TextSample("long-009", "车辆保养提醒显示轮胎胎压正常，机油寿命剩余百分之三十五，建议本周内预约门店检查。系统还会说明附近服务中心的营业时间和预计排队情况，这类信息播报适合验证安卓三点零AAR的长文本性能。" + LENGTH_SUFFIX),
            TextSample("long-010", "应用安全中心发现一个新的登录请求，地点与常用城市不完全一致。为了保护账号安全，请用户确认设备名称、登录时间和网络环境，如果不是本人操作需要立即修改密码并退出所有会话。" + LENGTH_SUFFIX),
        )
    }
}
