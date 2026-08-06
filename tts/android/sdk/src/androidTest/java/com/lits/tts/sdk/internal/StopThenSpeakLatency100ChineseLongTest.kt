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

class StopThenSpeakLatency100ChineseLongTest {
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()
    private val outputDir = File(
        context.getExternalFilesDir(null) ?: context.filesDir,
        "stop-speak-latency-100-zh-long",
    ).apply { mkdirs() }
    private val runId = "stop-speak-zh-long-100-${System.currentTimeMillis()}"
    private val samples = buildSamples()

    @Test
    fun stopThenSpeakLatencyAcross100ChineseLongSamples() {
        assertEquals("sample count", 100, samples.size)
        TextToSpeechSdk.setWorkPath(File(context.cacheDir, "stop-speak-zh-long-work").apply {
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
        engine.speak("这是中文长文本批量测试前的预热句，用来提前加载运行时状态。", speakParams(requestId))
        assertTrue("warmup synthesis complete timeout", listener.synthesisCompleteLatch.await(30, TimeUnit.SECONDS))
        engine.stop()
        listener.stopLatch.await(5, TimeUnit.SECONDS)
    }

    private fun runTrial(engine: TextToSpeechEngine, index: Int, text: String): TrialResult {
        val caseId = "zh-long-${index.toString().padStart(3, '0')}"
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

        listener.resetForSecondRequest()
        val secondSubmitAt = System.currentTimeMillis()
        engine.speak(text, speakParams(secondRequestId))
        val synthesisCompleteSeen = listener.synthesisCompleteLatch.await(SYNTHESIS_TIMEOUT_MS, TimeUnit.MILLISECONDS)
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
            secondFirstPacketMs = firstPacketMs,
            stopCallbackMs = if (onStopAt > 0L) onStopAt - stopCalledAt else -1L,
            stopToSecondSubmitMs = secondSubmitAt - stopCalledAt,
            stopCallToSecondFirstPacketMs = if (firstPacketMs >= 0L) secondSubmitAt + firstPacketMs - stopCalledAt else -1L,
            secondStartLatencyMs = listener.secondStartAtMs.takeIf { it > 0L }?.let { it - secondSubmitAt } ?: -1L,
            secondSynthesisMs = listener.secondCompleteSynthesisMs,
            secondAudioDurationMs = listener.secondCompleteAudioDurationMs,
            secondRtf = listener.secondCompleteRtf,
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
        File(outputDir, "samples.csv").writeText(
            buildString {
                appendLine("case_id,text_length,text")
                results.forEach { appendCsvLine(it.caseId, it.text.length.toString(), it.text) }
            },
            Charsets.UTF_8,
        )

        File(outputDir, "results.csv").writeText(
            buildString {
                appendLine(
                    "case_id,status,text_length,second_first_packet_ms,stop_callback_ms," +
                        "stop_to_second_submit_ms,stop_call_to_second_first_packet_ms,second_start_latency_ms," +
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
                        it.stopCallToSecondFirstPacketMs.toString(),
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
        File(outputDir, "TEST_REPORT_ZH.md").writeText(buildMarkdownReport(results, summary), Charsets.UTF_8)
        Log.i(TAG, "artifacts outputDir=${outputDir.absolutePath}")
    }

    private fun buildSummary(results: List<TrialResult>): JSONObject {
        val passed = results.filter { it.status.startsWith("PASS") }
        val firstStopNoAudio = results.filter { it.status == "PASS_WITH_FIRST_STOP_NO_AUDIO" }
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
            .put("restartAfterStopMs", 0)
            .put("total", results.size)
            .put("passed", passed.size)
            .put("failed", results.size - passed.size)
            .put("firstStopNoAudio", firstStopNoAudio.size)
            .put("textLength", metricJson(results.map { it.text.length.toLong() }.sorted()))
            .put("secondFirstPacketMs", metricJson(passed.map { it.secondFirstPacketMs }.filter { it >= 0L }.sorted()))
            .put("stopCallbackMs", metricJson(passed.map { it.stopCallbackMs }.filter { it >= 0L }.sorted()))
            .put("stopCallToSecondFirstPacketMs", metricJson(passed.map { it.stopCallToSecondFirstPacketMs }.filter { it >= 0L }.sorted()))
            .put("secondSynthesisMs", metricJson(passed.map { it.secondSynthesisMs }.filter { it >= 0L }.sorted()))
            .put("secondAudioDurationMs", metricJson(passed.map { it.secondAudioDurationMs }.filter { it >= 0L }.sorted()))
            .put("failures", JSONArray(results.filter { !it.status.startsWith("PASS") }.map { it.toJson() }))
            .put("firstStopNoAudioCases", JSONArray(firstStopNoAudio.map { it.caseId }))
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
        return values[((values.size - 1) * p).toInt().coerceIn(values.indices)]
    }

    private fun buildMarkdownReport(results: List<TrialResult>, summary: JSONObject): String {
        val fp = summary.getJSONObject("secondFirstPacketMs")
        val stopToPacket = summary.getJSONObject("stopCallToSecondFirstPacketMs")
        val stopCallback = summary.getJSONObject("stopCallbackMs")
        val textLen = summary.getJSONObject("textLength")
        return buildString {
            appendLine("# Android v2.5.4 中文长文本 Stop 后再次 Speak 时延测试报告")
            appendLine()
            appendLine("## 测试概述")
            appendLine()
            appendLine("- 设备：`MIA-AL00`，Android 12，SN `4EE9K25419002062`")
            appendLine("- 样例数量：`${results.size}` 条中文长文本")
            appendLine("- 流程：第一次 `speak()` -> `300 ms` 后 `stop()` -> `onStop` 后立即第二次 `speak()` -> 读取第二次 `SYNTHESIS_COMPLETE.firstPacketMs`")
            appendLine("- 运行参数：`zh-en`，voice `$VOICE_ID`，`SYNTHESIZE_AND_PLAY`，`PREEMPT`，`chunkSize=$CHUNK_SIZE`，`pcmQueueCapacity=$PCM_QUEUE_CAPACITY`，`speed=1.0`")
            appendLine("- 说明：本轮没有加入 stop 后再次 speak 的人为等待。")
            appendLine()
            appendLine("## 核心结果")
            appendLine()
            appendLine("- 第二次 `speak()` 有效样例：`${summary.getInt("passed")}/${summary.getInt("total")}`")
            appendLine("- 中文文本长度：min `${textLen.opt("min")}`，P50 `${textLen.opt("p50")}`，P95 `${textLen.opt("p95")}`，max `${textLen.opt("max")}`")
            appendLine("- 第二次 speak 首包：avg `${fmt(fp.optDouble("avg"))} ms`，P50 `${fp.opt("p50")} ms`，P95 `${fp.opt("p95")} ms`，max `${fp.opt("max")} ms`")
            appendLine("- `stop()` 调用到第二次首包：avg `${fmt(stopToPacket.optDouble("avg"))} ms`，P50 `${stopToPacket.opt("p50")} ms`，P95 `${stopToPacket.opt("p95")} ms`，max `${stopToPacket.opt("max")} ms`")
            appendLine("- `stop()` 调用到 `onStop`：avg `${fmt(stopCallback.optDouble("avg"))} ms`，P50 `${stopCallback.opt("p50")} ms`，P95 `${stopCallback.opt("p95")} ms`，max `${stopCallback.opt("max")} ms`")
            appendLine()
            appendLine("## 早停观察")
            appendLine()
            appendLine("- 第一次请求在 `300 ms` 被 stop 后，上报 `streaming playback produced no synthesized audio` 的样例数：`${summary.getInt("firstStopNoAudio")}`")
            appendLine("- 该事件表示第一次请求在被停止前尚未产出音频；不影响第二次 `speak()` 的首包统计。")
            appendLine()
            appendLine("## 测试产物")
            appendLine()
            appendLine("- 样例：`samples.csv`")
            appendLine("- 原始结果：`results.csv`")
            appendLine("- 统计摘要：`summary.json`")
            appendLine("- 中文报告：`TEST_REPORT_ZH.md`")
        }
    }

    private fun fmt(value: Double): String = String.format(Locale.US, "%.1f", value)

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
        @Volatile var secondCompleteFirstPacketMs: Long = -1L
        @Volatile var secondCompleteSynthesisMs: Long = -1L
        @Volatile var secondCompleteAudioDurationMs: Long = -1L
        @Volatile var secondCompleteRtf: Double = -1.0
        @Volatile var secondStartAtMs: Long = -1L
        @Volatile private var measuringSecond = false

        fun resetForSecondRequest() {
            secondCompleteFirstPacketMs = -1L
            secondCompleteSynthesisMs = -1L
            secondCompleteAudioDurationMs = -1L
            secondCompleteRtf = -1.0
            synthesisCompleteLatch = CountDownLatch(1)
            secondStopLatch = CountDownLatch(1)
            measuringSecond = true
        }

        override fun onStart(requestId: String, response: StartResponse) {
            if (measuringSecond) secondStartAtMs = System.currentTimeMillis()
        }

        override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) = Unit

        override fun onComplete(requestId: String, response: CompleteResponse) {
            if (response.type == CompleteType.SYNTHESIS_COMPLETE) {
                if (measuringSecond) {
                    secondCompleteFirstPacketMs = response.firstPacketMs
                    secondCompleteSynthesisMs = response.synthesisMs
                    secondCompleteAudioDurationMs = response.audioDurationMs
                    secondCompleteRtf = response.rtf
                }
                synthesisCompleteLatch.countDown()
            } else if (response.type == CompleteType.PLAYBACK_COMPLETE && measuringSecond) {
                secondStopLatch.countDown()
            }
        }

        override fun onStop(requestId: String, response: StopResponse) {
            stopEvents += StopEvent(requestId, System.currentTimeMillis())
            if (measuringSecond) secondStopLatch.countDown() else stopLatch.countDown()
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
        val secondFirstPacketMs: Long,
        val stopCallbackMs: Long,
        val stopToSecondSubmitMs: Long,
        val stopCallToSecondFirstPacketMs: Long,
        val secondStartLatencyMs: Long,
        val secondSynthesisMs: Long,
        val secondAudioDurationMs: Long,
        val secondRtf: Double,
        val message: String,
    ) {
        fun toJson(): JSONObject = JSONObject()
            .put("caseId", caseId)
            .put("status", status)
            .put("text", text)
            .put("secondFirstPacketMs", secondFirstPacketMs)
            .put("stopCallbackMs", stopCallbackMs)
            .put("stopCallToSecondFirstPacketMs", stopCallToSecondFirstPacketMs)
            .put("message", message)

        fun toLogLine(): String =
            "case=$caseId status=$status secondFirstPacketMs=$secondFirstPacketMs " +
                "stopCallToSecondFirstPacketMs=$stopCallToSecondFirstPacketMs " +
                "synthesisMs=$secondSynthesisMs audioDurationMs=$secondAudioDurationMs message=$message"
    }

    private fun buildSamples(): List<String> {
        val scenes = listOf(
            "早高峰通勤提醒", "会议纪要朗读", "智能座舱播报", "家庭助手通知", "客服工单摘要",
            "导航路线说明", "设备状态巡检", "应用市场推荐", "外卖订单播报", "出行行程确认",
        )
        val places = listOf("深圳南山区", "上海浦东新区", "北京海淀区", "广州天河区", "杭州滨江区")
        val brands = listOf("华为", "小米", "荣耀", "比亚迪", "蔚来", "小鹏", "理想", "大疆", "美团", "抖音")
        val actions = listOf(
            "需要先播报当前状态，再提醒用户确认下一步操作",
            "需要覆盖较长句子的分段、停顿和连续合成稳定性",
            "需要在用户点击停止后立刻响应新的播放请求",
            "需要混合数字、英文品牌和中文地名进行前端归一化",
            "需要观察首包、合成耗时、音频时长和取消路径是否稳定",
        )
        return (0 until 100).map { index ->
            val n = (index + 1).toString().padStart(3, '0')
            val scene = scenes[index % scenes.size]
            val place = places[index % places.size]
            val brand = brands[index % brands.size]
            val action = actions[index % actions.size]
            "样例$n，$scene。今天在$place 进行中文长文本 stop 后再次 speak 时延测试，" +
                "系统会先朗读一段较长内容，然后在三百毫秒时主动停止，再立即提交新的播放请求。" +
                "本条包含$brand、OpenAI、DeepSeek、HarmonyOS 以及编号A${1000 + index}，$action。" +
                "请记录第二次播放的首包时延、停止回调耗时、整体合成耗时，并确认没有阻塞下一次请求。"
        }
    }

    companion object {
        private const val TAG = "StopSpeakZhLong100"
        private const val LANGUAGE = "zh-en"
        private const val VOICE_ID = "lits-female-02"
        private const val CHUNK_SIZE = 50
        private const val PCM_QUEUE_CAPACITY = 32
        private const val STOP_AFTER_MS = 300L
        private const val STOP_TIMEOUT_MS = 5_000L
        private const val SYNTHESIS_TIMEOUT_MS = 45_000L
    }
}
