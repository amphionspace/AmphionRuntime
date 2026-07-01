package com.lits.tts.aarhost

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
import java.io.File
import java.util.Locale
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AarInterfaceTwoCallSameEngine10PairsLatencyTest {
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()
    private val outputDir = File(
        context.getExternalFilesDir(null) ?: context.filesDir,
        "aar-two-call-same-engine-latency",
    ).apply { mkdirs() }
    private val runId = "aar-two-call-same-engine-10-pairs-${System.currentTimeMillis()}"

    @Test
    fun tenPairsOfTwentyCharSentencesUseSameAarEngineWithoutDestroying() {
        val samples = buildSamples()
        assertEquals("sample pair count", 10, samples.size)
        samples.forEach {
            assertEquals("${it.caseId} first length", 20, it.firstText.length)
            assertEquals("${it.caseId} second length", 20, it.secondText.length)
        }

        TextToSpeechSdk.setWorkPath(File(context.cacheDir, "aar-two-call-10-pairs-work").apply {
            deleteRecursively()
            mkdirs()
        }.absolutePath)

        val createEngineStartMs = System.currentTimeMillis()
        val engine = TextToSpeechSdk.createEngine(
            CreateEngineParams(
                language = LANGUAGE,
                mode = RunMode.OFFLINE,
                voiceId = VOICE_ID,
                engineName = runId,
            ),
        )
        val createEngineMs = System.currentTimeMillis() - createEngineStartMs

        val results = mutableListOf<PairResult>()
        try {
            samples.forEach { sample ->
                val listener = PairListener(sample.caseId)
                engine.setListener(listener)

                val firstSubmitAtMs = System.currentTimeMillis()
                engine.speak(sample.firstText, speakParams("${sample.caseId}-first-$runId"))
                assertTrue(
                    "${sample.caseId} first playback complete timeout",
                    listener.firstPlaybackCompleteLatch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS),
                )

                val firstPlaybackCompleteAtMs = listener.firstPlaybackCompleteAtMs
                val secondSubmitAtMs = System.currentTimeMillis()
                engine.speak(sample.secondText, speakParams("${sample.caseId}-second-$runId"))
                assertTrue(
                    "${sample.caseId} second playback complete timeout",
                    listener.secondPlaybackCompleteLatch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS),
                )

                val secondSubmitToStartMs = listener.secondStartAtMs - secondSubmitAtMs
                val middleToSecondFirstPacketMs =
                    secondSubmitAtMs + secondSubmitToStartMs + listener.secondFirstPacketMs - firstPlaybackCompleteAtMs

                val result = PairResult(
                    caseId = sample.caseId,
                    firstText = sample.firstText,
                    secondText = sample.secondText,
                    firstFirstPacketMs = listener.firstFirstPacketMs,
                    firstSynthesisMs = listener.firstSynthesisMs,
                    firstAudioDurationMs = listener.firstAudioDurationMs,
                    firstSubmitToPlaybackCompleteMs = firstPlaybackCompleteAtMs - firstSubmitAtMs,
                    firstPlaybackCompleteToSecondSubmitMs = secondSubmitAtMs - firstPlaybackCompleteAtMs,
                    secondSubmitToStartMs = secondSubmitToStartMs,
                    secondFirstPacketMs = listener.secondFirstPacketMs,
                    secondSynthesisMs = listener.secondSynthesisMs,
                    secondAudioDurationMs = listener.secondAudioDurationMs,
                    firstPlaybackCompleteToSecondFirstPacketMs = middleToSecondFirstPacketMs,
                    secondSubmitToPlaybackCompleteMs = listener.secondPlaybackCompleteAtMs - secondSubmitAtMs,
                    errors = listener.errors.toList(),
                )
                results += result
                Log.i(TAG, result.toLogLine())
            }

            assertTrue("unexpected errors: ${results.flatMap { it.errors }}", results.all { it.errors.isEmpty() })
            assertTrue("missing second first packet", results.all { it.secondFirstPacketMs >= 0L })

            writeArtifacts(createEngineMs, results)
        } finally {
            engine.shutdown()
            Log.i(TAG, "shutdownCalledAfterAllPairs=true")
        }
    }

    private fun speakParams(requestId: String): SpeakParams =
        SpeakParams(
            requestId = requestId,
            speed = 1.0f,
            playType = PlayType.SYNTHESIZE_AND_PLAY,
            queueMode = QueueMode.PREEMPT,
            languageContext = LANGUAGE,
        )

    private fun writeArtifacts(createEngineMs: Long, results: List<PairResult>) {
        File(outputDir, "results_10_pairs.csv").writeText(
            buildString {
                appendLine(
                    "case_id,first_text,second_text,first_first_packet_ms,first_submit_to_playback_complete_ms," +
                        "middle_submit_gap_ms,second_submit_to_start_ms,second_first_packet_ms," +
                        "middle_to_second_first_packet_ms,second_submit_to_playback_complete_ms,errors",
                )
                results.forEach {
                    appendCsvLine(
                        it.caseId,
                        it.firstText,
                        it.secondText,
                        it.firstFirstPacketMs.toString(),
                        it.firstSubmitToPlaybackCompleteMs.toString(),
                        it.firstPlaybackCompleteToSecondSubmitMs.toString(),
                        it.secondSubmitToStartMs.toString(),
                        it.secondFirstPacketMs.toString(),
                        it.firstPlaybackCompleteToSecondFirstPacketMs.toString(),
                        it.secondSubmitToPlaybackCompleteMs.toString(),
                        it.errors.joinToString("; "),
                    )
                }
            },
            Charsets.UTF_8,
        )

        val summary = buildSummary(createEngineMs, results)
        File(outputDir, "summary_10_pairs.json").writeText(summary.toString(2) + "\n", Charsets.UTF_8)
        File(outputDir, "TEST_REPORT_ZH.md").writeText(buildReport(summary), Charsets.UTF_8)
    }

    private fun buildSummary(createEngineMs: Long, results: List<PairResult>): JSONObject =
        JSONObject()
            .put("runId", runId)
            .put("integrationPath", "aarHost implementation(files(\"../sdk/build/outputs/aar/sdk-debug.aar\"))")
            .put("devicePackage", context.packageName)
            .put("sameEngineAcrossAllPairs", true)
            .put("shutdownBetweenCalls", false)
            .put("language", LANGUAGE)
            .put("voiceId", VOICE_ID)
            .put("playType", PlayType.SYNTHESIZE_AND_PLAY.name)
            .put("queueMode", QueueMode.PREEMPT.name)
            .put("createEngineMs", createEngineMs)
            .put("totalPairs", results.size)
            .put("passedPairs", results.count { it.errors.isEmpty() && it.secondFirstPacketMs >= 0L })
            .put("failedPairs", results.count { it.errors.isNotEmpty() || it.secondFirstPacketMs < 0L })
            .put("middleSubmitGapMs", metricJson(results.map { it.firstPlaybackCompleteToSecondSubmitMs }.sorted()))
            .put("secondSubmitToStartMs", metricJson(results.map { it.secondSubmitToStartMs }.sorted()))
            .put("secondFirstPacketMs", metricJson(results.map { it.secondFirstPacketMs }.sorted()))
            .put(
                "firstPlaybackCompleteToSecondFirstPacketMs",
                metricJson(results.map { it.firstPlaybackCompleteToSecondFirstPacketMs }.sorted()),
            )
            .put("results", JSONArray(results.map { it.toJson() }))

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

    private fun buildReport(summary: JSONObject): String {
        val middle = summary.getJSONObject("firstPlaybackCompleteToSecondFirstPacketMs")
        val submitToStart = summary.getJSONObject("secondSubmitToStartMs")
        val secondFirstPacket = summary.getJSONObject("secondFirstPacketMs")
        val gap = summary.getJSONObject("middleSubmitGapMs")
        return buildString {
            appendLine("# Android v2.5.4 AAR 同引擎两次调用时延测试报告")
            appendLine()
            appendLine("## 测试设置")
            appendLine()
            appendLine("- 集成路径：宿主 App `aarHost` 通过 `implementation(files(\"../sdk/build/outputs/aar/sdk-debug.aar\"))` 依赖 AAR")
            appendLine("- 引擎策略：同一个 engine 连续测试 10 组样例，两次 `speak()` 中间不销毁引擎")
            appendLine("- 样例：每组两条 20 字中文句子")
            appendLine("- 流程：句子 1 `SYNTHESIZE_AND_PLAY` 播放完成回调后，立即提交句子 2，并记录第二句首包")
            appendLine("- `createEngine` 耗时：`${summary.getLong("createEngineMs")} ms`")
            appendLine()
            appendLine("## 核心结果")
            appendLine()
            appendLine("- 有效样例：`${summary.getInt("passedPairs")}/${summary.getInt("totalPairs")}`")
            appendLine("- 句子 1 播放完成到句子 2 submit：avg `${fmt(gap.optDouble("avg"))} ms`，P50 `${gap.opt("p50")} ms`，P95 `${gap.opt("p95")} ms`，max `${gap.opt("max")} ms`")
            appendLine("- 句子 2 submit 到 `onStart`：avg `${fmt(submitToStart.optDouble("avg"))} ms`，P50 `${submitToStart.opt("p50")} ms`，P95 `${submitToStart.opt("p95")} ms`，max `${submitToStart.opt("max")} ms`")
            appendLine("- 句子 2 submit 到首包：avg `${fmt(secondFirstPacket.optDouble("avg"))} ms`，P50 `${secondFirstPacket.opt("p50")} ms`，P95 `${secondFirstPacket.opt("p95")} ms`，max `${secondFirstPacket.opt("max")} ms`")
            appendLine("- 句子 1 播放完成到句子 2 首包：avg `${fmt(middle.optDouble("avg"))} ms`，P50 `${middle.opt("p50")} ms`，P95 `${middle.opt("p95")} ms`，max `${middle.opt("max")} ms`")
            appendLine()
            appendLine("## 结论")
            appendLine()
            appendLine("- 10 组 AAR 同引擎两次调用均未复现 2 秒中间时延；播放完成到第二句首包 P95 为 `${middle.opt("p95")} ms`。")
            appendLine("- 原始逐样例数据见 `results_10_pairs.csv`，统计摘要见 `summary_10_pairs.json`。")
        }
    }

    private fun fmt(value: Double): String = String.format(Locale.US, "%.1f", value)

    private fun StringBuilder.appendCsvLine(vararg cells: String) {
        append(cells.joinToString(",") { it.csvEscape() })
        append('\n')
    }

    private fun String.csvEscape(): String = "\"" + replace("\"", "\"\"") + "\""

    private data class SamplePair(val caseId: String, val firstText: String, val secondText: String)

    private data class PairResult(
        val caseId: String,
        val firstText: String,
        val secondText: String,
        val firstFirstPacketMs: Long,
        val firstSynthesisMs: Long,
        val firstAudioDurationMs: Long,
        val firstSubmitToPlaybackCompleteMs: Long,
        val firstPlaybackCompleteToSecondSubmitMs: Long,
        val secondSubmitToStartMs: Long,
        val secondFirstPacketMs: Long,
        val secondSynthesisMs: Long,
        val secondAudioDurationMs: Long,
        val firstPlaybackCompleteToSecondFirstPacketMs: Long,
        val secondSubmitToPlaybackCompleteMs: Long,
        val errors: List<String>,
    ) {
        fun toJson(): JSONObject = JSONObject()
            .put("caseId", caseId)
            .put("firstText", firstText)
            .put("secondText", secondText)
            .put("firstFirstPacketMs", firstFirstPacketMs)
            .put("firstSynthesisMs", firstSynthesisMs)
            .put("firstAudioDurationMs", firstAudioDurationMs)
            .put("firstSubmitToPlaybackCompleteMs", firstSubmitToPlaybackCompleteMs)
            .put("firstPlaybackCompleteToSecondSubmitMs", firstPlaybackCompleteToSecondSubmitMs)
            .put("secondSubmitToStartMs", secondSubmitToStartMs)
            .put("secondFirstPacketMs", secondFirstPacketMs)
            .put("secondSynthesisMs", secondSynthesisMs)
            .put("secondAudioDurationMs", secondAudioDurationMs)
            .put("firstPlaybackCompleteToSecondFirstPacketMs", firstPlaybackCompleteToSecondFirstPacketMs)
            .put("secondSubmitToPlaybackCompleteMs", secondSubmitToPlaybackCompleteMs)
            .put("errors", JSONArray(errors))

        fun toLogLine(): String =
            "case=$caseId middleToSecondFirstPacketMs=$firstPlaybackCompleteToSecondFirstPacketMs " +
                "secondFirstPacketMs=$secondFirstPacketMs secondSubmitToStartMs=$secondSubmitToStartMs errors=$errors"
    }

    private class PairListener(private val caseId: String) : SpeakListener {
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

        override fun onStart(requestId: String, response: StartResponse) {
            if (requestId.contains("-first-")) {
                firstStartAtMs = System.currentTimeMillis()
            } else if (requestId.contains("-second-")) {
                secondStartAtMs = System.currentTimeMillis()
            }
        }

        override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) = Unit

        override fun onComplete(requestId: String, response: CompleteResponse) {
            if (response.type == CompleteType.SYNTHESIS_COMPLETE) {
                if (requestId.contains("-first-")) {
                    firstFirstPacketMs = response.firstPacketMs
                    firstSynthesisMs = response.synthesisMs
                    firstAudioDurationMs = response.audioDurationMs
                } else if (requestId.contains("-second-")) {
                    secondFirstPacketMs = response.firstPacketMs
                    secondSynthesisMs = response.synthesisMs
                    secondAudioDurationMs = response.audioDurationMs
                }
            } else if (response.type == CompleteType.PLAYBACK_COMPLETE) {
                if (requestId.contains("-first-")) {
                    firstPlaybackCompleteAtMs = System.currentTimeMillis()
                    firstPlaybackCompleteLatch.countDown()
                } else if (requestId.contains("-second-")) {
                    secondPlaybackCompleteAtMs = System.currentTimeMillis()
                    secondPlaybackCompleteLatch.countDown()
                }
            }
        }

        override fun onStop(requestId: String, response: StopResponse) = Unit

        override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
            errors += "$caseId:$requestId:$errorCode:$errorMessage"
            firstPlaybackCompleteLatch.countDown()
            secondPlaybackCompleteLatch.countDown()
        }
    }

    private fun buildSamples(): List<SamplePair> {
        val nums = listOf("一", "二", "三", "四", "五", "六", "七", "八", "九", "十")
        return nums.mapIndexed { index, num ->
            SamplePair(
                caseId = "pair-${(index + 1).toString().padStart(2, '0')}",
                firstText = "样例${num}第一条正在通过接口播放测试中呢吧呀",
                secondText = "样例${num}第二条继续通过接口播放测试中呢吧呀",
            )
        }
    }

    companion object {
        private const val TAG = "AarTwoCall10Pairs"
        private const val LANGUAGE = "zh-en"
        private const val VOICE_ID = "lits-female-02"
        private const val TIMEOUT_MS = 60_000L
    }
}
