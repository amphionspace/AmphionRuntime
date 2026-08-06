package com.lits.tts.aarhost

import android.os.Bundle
import android.util.Log
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
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
import java.util.Locale
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Test

class AarInterfaceLongTextTwoCall50BatchTest {
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()
    private val outputDir = File(
        context.getExternalFilesDir(null) ?: context.filesDir,
        "aar-long-text-two-call-50-batch",
    ).apply { mkdirs() }
    private val args: Bundle = InstrumentationRegistry.getArguments()
    private val runId = "aar-long-two-call-batch-${System.currentTimeMillis()}"

    @Test
    fun longTextTwoSpeakLatencyBatch() {
        val pairCount = args.getString("pairCount")?.toIntOrNull()?.coerceAtLeast(1) ?: DEFAULT_PAIR_COUNT
        val chunkSizes = args.getString("chunkSizes")
            ?.split(",")
            ?.mapNotNull { it.trim().toIntOrNull() }
            ?.filter { it > 0 }
            ?.takeIf { it.isNotEmpty() }
            ?: DEFAULT_CHUNK_SIZES
        val firstChunkMode = args.getString("firstChunkMode") ?: "same"
        val samplePairs = buildSamplePairs(pairCount)
        samplePairs.forEach {
            assertTrue("${it.caseId} first text length=${it.firstText.length}", it.firstText.length > 100)
            assertTrue("${it.caseId} second text length=${it.secondText.length}", it.secondText.length > 100)
        }

        TextToSpeechSdk.setWorkPath(File(context.cacheDir, "aar-long-two-call-50-batch-work").apply {
            deleteRecursively()
            mkdirs()
        }.absolutePath)

        val results = mutableListOf<PairResult>()
        chunkSizes.forEach { chunkSize ->
            val config = ChunkConfig(
                chunkSize = chunkSize,
                firstChunkSize = if (firstChunkMode == "50") minOf(50, chunkSize) else chunkSize,
            )
            TextToSpeechSdk.createEngine(
                CreateEngineParams(
                    language = LANGUAGE,
                    mode = RunMode.OFFLINE,
                    voiceId = VOICE_ID,
                    engineName = "$runId-${config.caseId}",
                ),
            ).useEngine { engine ->
                samplePairs.forEachIndexed { index, pair ->
                    val result = runPair(
                        engine = engine,
                        config = config,
                        pair = pair,
                        ordinal = index + 1,
                    )
                    results += result
                    writeArtifacts(pairCount, chunkSizes, firstChunkMode, results)
                    Log.i(TAG, result.toLogLine())
                }
            }
        }

        val summary = writeArtifacts(pairCount, chunkSizes, firstChunkMode, results)
        Log.i(TAG, "summary=$summary")

        assertTrue("unexpected errors: ${results.flatMap { it.errors }}", results.all { it.errors.isEmpty() })
        assertTrue("missing second first packet", results.all { it.secondFirstPacketMs >= 0L })
        assertTrue("missing playback complete", results.all { it.secondSubmitToPlaybackCompleteMs >= 0L })
    }

    private fun runPair(
        engine: com.lits.tts.sdk.TextToSpeechEngine,
        config: ChunkConfig,
        pair: SamplePair,
        ordinal: Int,
    ): PairResult {
        val listener = PairListener(config, pair.caseId)
        engine.setListener(listener)
        val firstRequestId = "${config.caseId}-${pair.caseId}-call1-$runId"
        val secondRequestId = "${config.caseId}-${pair.caseId}-call2-$runId"

        val firstSubmitAtMs = System.currentTimeMillis()
        engine.speak(pair.firstText, speakParams(firstRequestId, config))
        assertTrue(
            "${config.caseId} ${pair.caseId} first playback complete timeout",
            listener.firstPlaybackCompleteLatch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS),
        )

        val firstPlaybackCompleteAtMs = listener.firstPlaybackCompleteAtMs
        val secondSubmitAtMs = System.currentTimeMillis()
        engine.speak(pair.secondText, speakParams(secondRequestId, config))
        assertTrue(
            "${config.caseId} ${pair.caseId} second playback complete timeout",
            listener.secondPlaybackCompleteLatch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS),
        )

        val secondSubmitToStartMs = listener.secondStartAtMs - secondSubmitAtMs
        val completeToSecondFirstPacketMs =
            secondSubmitAtMs + secondSubmitToStartMs + listener.secondFirstPacketMs - firstPlaybackCompleteAtMs

        return PairResult(
            caseId = pair.caseId,
            ordinal = ordinal,
            chunkSize = config.chunkSize,
            firstChunkSize = config.firstChunkSize,
            effectiveStreamingChunkSize = listener.secondEffectiveStreamingChunkSize,
            effectivePcmQueueCapacity = listener.secondEffectivePcmQueueCapacity,
            firstTextLength = pair.firstText.length,
            secondTextLength = pair.secondText.length,
            firstFirstPacketMs = listener.firstFirstPacketMs,
            firstSynthesisMs = listener.firstSynthesisMs,
            firstAudioDurationMs = listener.firstAudioDurationMs,
            firstSubmitToPlaybackCompleteMs = firstPlaybackCompleteAtMs - firstSubmitAtMs,
            firstPlaybackCompleteToSecondSubmitMs = secondSubmitAtMs - firstPlaybackCompleteAtMs,
            secondSubmitToStartMs = secondSubmitToStartMs,
            secondFirstPacketMs = listener.secondFirstPacketMs,
            secondSynthesisMs = listener.secondSynthesisMs,
            secondAudioDurationMs = listener.secondAudioDurationMs,
            secondPlaybackStartMs = listener.secondPlaybackStartMs,
            completeToSecondFirstPacketMs = completeToSecondFirstPacketMs,
            secondSubmitToPlaybackCompleteMs = listener.secondPlaybackCompleteAtMs - secondSubmitAtMs,
            firstProfilingInfo = listener.firstProfilingInfo,
            secondProfilingInfo = listener.secondProfilingInfo,
            errors = listener.errors.toList(),
        )
    }

    private fun speakParams(requestId: String, config: ChunkConfig): SpeakParams =
        SpeakParams(
            requestId = requestId,
            speed = 1.0f,
            playType = PlayType.SYNTHESIZE_AND_PLAY,
            queueMode = QueueMode.PREEMPT,
            languageContext = LANGUAGE,
            streamingConfig = TtsStreamingConfig(
                chunkSize = config.chunkSize,
                firstChunkSize = config.firstChunkSize,
                pcmQueueCapacity = PCM_QUEUE_CAPACITY,
            ),
        )

    private fun com.lits.tts.sdk.TextToSpeechEngine.useEngine(block: (com.lits.tts.sdk.TextToSpeechEngine) -> Unit) {
        try {
            block(this)
        } finally {
            shutdown()
        }
    }

    private fun buildSummary(
        pairCount: Int,
        chunkSizes: List<Int>,
        firstChunkMode: String,
        results: List<PairResult>,
    ): JSONObject {
        val grouped = results.groupBy { it.chunkSize }
        val chunkSummaries = JSONObject()
        grouped.toSortedMap().forEach { (chunkSize, rows) ->
            chunkSummaries.put(
                chunkSize.toString(),
                JSONObject()
                    .put("count", rows.size)
                    .put("firstChunkSize", rows.firstOrNull()?.firstChunkSize ?: JSONObject.NULL)
                    .put("completeToSecondFirstPacketMs", metricJson(rows.map { it.completeToSecondFirstPacketMs }.sorted()))
                    .put("secondFirstPacketMs", metricJson(rows.map { it.secondFirstPacketMs }.sorted()))
                    .put("secondPlaybackStartMs", metricJson(rows.map { it.secondPlaybackStartMs }.sorted()))
                    .put("secondSynthesisMs", metricJson(rows.map { it.secondSynthesisMs }.sorted()))
                    .put("secondAudioDurationMs", metricJson(rows.map { it.secondAudioDurationMs }.sorted()))
                    .put("submitGapMs", metricJson(rows.map { it.firstPlaybackCompleteToSecondSubmitMs }.sorted()))
                    .put("submitToStartMs", metricJson(rows.map { it.secondSubmitToStartMs }.sorted())),
            )
        }
        return JSONObject()
            .put("runId", runId)
            .put("integrationPath", "aarHost implementation(files(\"../sdk/build/outputs/aar/sdk-release.aar\"))")
            .put("devicePackage", context.packageName)
            .put("language", LANGUAGE)
            .put("voiceId", VOICE_ID)
            .put("playType", PlayType.SYNTHESIZE_AND_PLAY.name)
            .put("queueMode", QueueMode.PREEMPT.name)
            .put("pcmQueueCapacity", PCM_QUEUE_CAPACITY)
            .put("pairCountPerChunk", pairCount)
            .put("chunkSizes", JSONArray(chunkSizes))
            .put("firstChunkMode", firstChunkMode)
            .put("textLength", metricJson(results.map { it.secondTextLength.toLong() }.sorted()))
            .put("chunkSummaries", chunkSummaries)
            .put("results", JSONArray(results.map { it.toJson() }))
    }

    private fun writeArtifacts(
        pairCount: Int,
        chunkSizes: List<Int>,
        firstChunkMode: String,
        results: List<PairResult>,
    ): JSONObject {
        val summary = buildSummary(pairCount, chunkSizes, firstChunkMode, results)
        File(outputDir, "summary_long_text_50_batch.json").writeText(summary.toString(2) + "\n", Charsets.UTF_8)
        File(outputDir, "results_long_text_50_batch.csv").writeText(buildCsv(results), Charsets.UTF_8)
        File(outputDir, "TEST_REPORT_ZH.md").writeText(buildReport(summary), Charsets.UTF_8)
        return summary
    }

    private fun buildCsv(results: List<PairResult>): String = buildString {
        appendLine(
            "case_id,ordinal,chunk_size,first_chunk_size,effective_chunk_size,effective_pcm_queue_capacity," +
                "first_text_length,second_text_length,first_first_packet_ms,first_synthesis_ms,first_audio_duration_ms," +
                "first_submit_to_playback_complete_ms,complete_to_second_submit_ms,second_submit_to_start_ms," +
                "second_first_packet_ms,second_synthesis_ms,second_audio_duration_ms,second_playback_start_ms," +
                "complete_to_second_first_packet_ms,second_submit_to_playback_complete_ms,first_profiling_info,second_profiling_info,errors",
        )
        results.forEach {
            appendCsvLine(
                it.caseId,
                it.ordinal.toString(),
                it.chunkSize.toString(),
                it.firstChunkSize.toString(),
                it.effectiveStreamingChunkSize.toString(),
                it.effectivePcmQueueCapacity.toString(),
                it.firstTextLength.toString(),
                it.secondTextLength.toString(),
                it.firstFirstPacketMs.toString(),
                it.firstSynthesisMs.toString(),
                it.firstAudioDurationMs.toString(),
                it.firstSubmitToPlaybackCompleteMs.toString(),
                it.firstPlaybackCompleteToSecondSubmitMs.toString(),
                it.secondSubmitToStartMs.toString(),
                it.secondFirstPacketMs.toString(),
                it.secondSynthesisMs.toString(),
                it.secondAudioDurationMs.toString(),
                it.secondPlaybackStartMs.toString(),
                it.completeToSecondFirstPacketMs.toString(),
                it.secondSubmitToPlaybackCompleteMs.toString(),
                it.firstProfilingInfo,
                it.secondProfilingInfo,
                it.errors.joinToString("; "),
            )
        }
    }

    private fun buildReport(summary: JSONObject): String = buildString {
        appendLine("# Android v3.0 AAR 长文本两次 speak 50 条批测报告")
        appendLine()
        appendLine("## 测试口径")
        appendLine()
        appendLine("- 每个 chunk 配置测试 `${summary.getInt("pairCountPerChunk")}` 组长文本对；每组包含两段超过 100 字文本。")
        appendLine("- 每组流程：长文本 1 `SYNTHESIZE_AND_PLAY` 播放完成后，立即调用长文本 2 的 `speak()`。")
        appendLine("- 间隔计算：`firstPlaybackCompleteToSecondFirstPacketMs = secondSubmitAtMs + secondSubmitToStartMs + secondFirstPacketMs - firstPlaybackCompleteAtMs`。")
        appendLine("- 这个时间表示“长文本 1 播放完成回调到长文本 2 首个 PCM chunk 生成”的间隔；其中 submit gap 和 submit->onStart 也单独统计。")
        appendLine("- AAR 接口：`SpeakParams.streamingConfig = TtsStreamingConfig(chunkSize, firstChunkSize, pcmQueueCapacity)`。")
        appendLine("- PCM queue capacity：`${summary.getInt("pcmQueueCapacity")}`；firstChunkMode：`${summary.getString("firstChunkMode")}`。")
        appendLine()
        appendLine("## 汇总结果")
        appendLine()
        val chunkSummaries = summary.getJSONObject("chunkSummaries")
        chunkSummaries.keys().asSequence().map { it.toInt() }.sorted().forEach { chunk ->
            val item = chunkSummaries.getJSONObject(chunk.toString())
            val gap = item.getJSONObject("completeToSecondFirstPacketMs")
            val secondFirstPacket = item.getJSONObject("secondFirstPacketMs")
            val submitGap = item.getJSONObject("submitGapMs")
            val submitToStart = item.getJSONObject("submitToStartMs")
            appendLine("- chunk `$chunk`：count `${item.getInt("count")}`，firstChunk `${item.opt("firstChunkSize")}`；播放完成到第二段首包 avg `${fmt(gap.optDouble("avg"))} ms`，P50 `${gap.opt("p50")} ms`，P95 `${gap.opt("p95")} ms`，max `${gap.opt("max")} ms`。")
            appendLine("  - 第二段 submit 到首包 avg `${fmt(secondFirstPacket.optDouble("avg"))} ms`，P50 `${secondFirstPacket.opt("p50")} ms`，P95 `${secondFirstPacket.opt("p95")} ms`。")
            appendLine("  - 播放完成到第二段 submit avg `${fmt(submitGap.optDouble("avg"))} ms`；第二段 submit 到 onStart avg `${fmt(submitToStart.optDouble("avg"))} ms`。")
        }
        appendLine()
        appendLine("## 原始数据")
        appendLine()
        appendLine("- `summary_long_text_50_batch.json`")
        appendLine("- `results_long_text_50_batch.csv`")
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

    private fun fmt(value: Double): String = String.format(Locale.US, "%.1f", value)

    private fun StringBuilder.appendCsvLine(vararg cells: String) {
        append(cells.joinToString(",") { it.csvEscape() })
        append('\n')
    }

    private fun String.csvEscape(): String = "\"" + replace("\"", "\"\"") + "\""

    private data class ChunkConfig(val chunkSize: Int, val firstChunkSize: Int) {
        val caseId: String = "chunk-$chunkSize-first-$firstChunkSize"
    }

    private data class SamplePair(val caseId: String, val firstText: String, val secondText: String)

    private data class PairResult(
        val caseId: String,
        val ordinal: Int,
        val chunkSize: Int,
        val firstChunkSize: Int,
        val effectiveStreamingChunkSize: Int,
        val effectivePcmQueueCapacity: Int,
        val firstTextLength: Int,
        val secondTextLength: Int,
        val firstFirstPacketMs: Long,
        val firstSynthesisMs: Long,
        val firstAudioDurationMs: Long,
        val firstSubmitToPlaybackCompleteMs: Long,
        val firstPlaybackCompleteToSecondSubmitMs: Long,
        val secondSubmitToStartMs: Long,
        val secondFirstPacketMs: Long,
        val secondSynthesisMs: Long,
        val secondAudioDurationMs: Long,
        val secondPlaybackStartMs: Long,
        val completeToSecondFirstPacketMs: Long,
        val secondSubmitToPlaybackCompleteMs: Long,
        val firstProfilingInfo: String,
        val secondProfilingInfo: String,
        val errors: List<String>,
    ) {
        fun toJson(): JSONObject = JSONObject()
            .put("caseId", caseId)
            .put("ordinal", ordinal)
            .put("chunkSize", chunkSize)
            .put("firstChunkSize", firstChunkSize)
            .put("effectiveStreamingChunkSize", effectiveStreamingChunkSize)
            .put("effectivePcmQueueCapacity", effectivePcmQueueCapacity)
            .put("firstTextLength", firstTextLength)
            .put("secondTextLength", secondTextLength)
            .put("firstFirstPacketMs", firstFirstPacketMs)
            .put("firstSynthesisMs", firstSynthesisMs)
            .put("firstAudioDurationMs", firstAudioDurationMs)
            .put("firstSubmitToPlaybackCompleteMs", firstSubmitToPlaybackCompleteMs)
            .put("firstPlaybackCompleteToSecondSubmitMs", firstPlaybackCompleteToSecondSubmitMs)
            .put("secondSubmitToStartMs", secondSubmitToStartMs)
            .put("secondFirstPacketMs", secondFirstPacketMs)
            .put("secondSynthesisMs", secondSynthesisMs)
            .put("secondAudioDurationMs", secondAudioDurationMs)
            .put("secondPlaybackStartMs", secondPlaybackStartMs)
            .put("completeToSecondFirstPacketMs", completeToSecondFirstPacketMs)
            .put("secondSubmitToPlaybackCompleteMs", secondSubmitToPlaybackCompleteMs)
            .put("firstProfilingInfo", firstProfilingInfo)
            .put("secondProfilingInfo", secondProfilingInfo)
            .put("errors", JSONArray(errors))

        fun toLogLine(): String =
            "case=$caseId ordinal=$ordinal chunk=$chunkSize firstChunk=$firstChunkSize " +
                "completeToSecondFirstPacketMs=$completeToSecondFirstPacketMs secondFirstPacketMs=$secondFirstPacketMs " +
                "secondPlaybackStartMs=$secondPlaybackStartMs errors=$errors"
    }

    private class PairListener(private val config: ChunkConfig, private val caseId: String) : SpeakListener {
        val firstPlaybackCompleteLatch = CountDownLatch(1)
        val secondPlaybackCompleteLatch = CountDownLatch(1)
        val errors = mutableListOf<String>()
        @Volatile var firstStartAtMs: Long = -1L
        @Volatile var secondStartAtMs: Long = -1L
        @Volatile var firstFirstPacketMs: Long = -1L
        @Volatile var secondFirstPacketMs: Long = -1L
        @Volatile var firstSynthesisMs: Long = -1L
        @Volatile var secondSynthesisMs: Long = -1L
        @Volatile var firstAudioDurationMs: Long = -1L
        @Volatile var secondAudioDurationMs: Long = -1L
        @Volatile var firstPlaybackCompleteAtMs: Long = -1L
        @Volatile var secondPlaybackCompleteAtMs: Long = -1L
        @Volatile var secondEffectiveStreamingChunkSize: Int = -1
        @Volatile var secondEffectivePcmQueueCapacity: Int = -1
        @Volatile var firstProfilingInfo: String = ""
        @Volatile var secondProfilingInfo: String = ""
        @Volatile var secondPlaybackStartMs: Long = -1L

        override fun onStart(requestId: String, response: StartResponse) {
            if (requestId.contains("-call1-")) {
                firstStartAtMs = System.currentTimeMillis()
            } else if (requestId.contains("-call2-")) {
                secondStartAtMs = System.currentTimeMillis()
                secondEffectiveStreamingChunkSize = response.streamingChunkSize
                secondEffectivePcmQueueCapacity = response.pcmQueueCapacity
            }
        }

        override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) = Unit

        override fun onComplete(requestId: String, response: CompleteResponse) {
            if (response.type == CompleteType.SYNTHESIS_COMPLETE) {
                if (requestId.contains("-call1-")) {
                    firstFirstPacketMs = response.firstPacketMs
                    firstSynthesisMs = response.synthesisMs
                    firstAudioDurationMs = response.audioDurationMs
                    firstProfilingInfo = response.profilingInfo
                } else if (requestId.contains("-call2-")) {
                    secondFirstPacketMs = response.firstPacketMs
                    secondSynthesisMs = response.synthesisMs
                    secondAudioDurationMs = response.audioDurationMs
                    secondProfilingInfo = response.profilingInfo
                    secondPlaybackStartMs = response.playbackStartMs
                }
            } else if (response.type == CompleteType.PLAYBACK_COMPLETE) {
                if (requestId.contains("-call1-")) {
                    firstPlaybackCompleteAtMs = System.currentTimeMillis()
                    firstPlaybackCompleteLatch.countDown()
                } else if (requestId.contains("-call2-")) {
                    secondPlaybackCompleteAtMs = System.currentTimeMillis()
                    secondPlaybackCompleteLatch.countDown()
                }
            }
        }

        override fun onStop(requestId: String, response: StopResponse) = Unit

        override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
            errors += "${config.caseId}:$caseId:$requestId:$errorCode:$errorMessage"
            firstPlaybackCompleteLatch.countDown()
            secondPlaybackCompleteLatch.countDown()
        }
    }

    private fun buildSamplePairs(count: Int): List<SamplePair> {
        val scenes = listOf("导航播报", "会议提醒", "天气预警", "系统通知", "待办事项", "车载助手", "客服提示", "日程播报", "路线规划", "应用提醒")
        val places = listOf("机场高速", "办公室", "地铁站", "会议室", "学校门口", "园区大厅", "停车场", "高铁站", "社区服务中心", "研发实验室")
        val actions = listOf("请保持当前路线并关注前方路况", "请确认会议材料是否已经同步", "请注意稍后可能出现降雨", "请检查后台任务是否已经完成", "请在安全位置查看详细信息")
        return (0 until count).map { index ->
            val n = (index + 1).toString().padStart(2, '0')
            val scene = scenes[index % scenes.size]
            val place = places[(index * 3) % places.size]
            val action = actions[(index * 5) % actions.size]
            val first = "样例$n 第一段长文本用于$scene 的连续播放测试，当前地点是$place。" +
                "我们需要确认安卓三点零AAR接口在第一段内容完整播放结束之后，可以稳定释放播放状态并准备下一次调用。" +
                "这段文字故意超过一百个汉字，包含业务说明、状态提示和编号B$n，$action。"
            val second = "样例$n 第二段长文本紧接着调用speak，用来测量两段长文本之间的实际首包间隔。" +
                "它保持同一个引擎、同一个说话人和同样的队列策略，同时覆盖较长输入、前端分段、流式解码和内部播放链路。" +
                "如果第二段首包明显变慢，报告会结合profiling拆分说明具体耗时来源。"
            SamplePair(caseId = "long-$n", firstText = first, secondText = second)
        }
    }

    companion object {
        private const val TAG = "AarLong50Batch"
        private const val LANGUAGE = "zh-en"
        private const val VOICE_ID = "lits-female-02"
        private const val PCM_QUEUE_CAPACITY = 128
        private const val TIMEOUT_MS = 240_000L
        private const val DEFAULT_PAIR_COUNT = 50
        private val DEFAULT_CHUNK_SIZES = listOf(50, 100)
    }
}
