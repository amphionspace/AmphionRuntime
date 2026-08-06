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

class AarInterfaceChunkConfigTwoCallLatencyTest {
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()
    private val outputDir = File(
        context.getExternalFilesDir(null) ?: context.filesDir,
        "aar-chunk-config-two-call-latency",
    ).apply { mkdirs() }
    private val runId = "aar-chunk-config-two-call-${System.currentTimeMillis()}"

    @Test
    fun chunk50And100UseAarStreamingConfigForTwoSpeakCalls() {
        assertEquals(20, FIRST_TEXT.length)
        assertEquals(20, SECOND_TEXT.length)

        TextToSpeechSdk.setWorkPath(File(context.cacheDir, "aar-chunk-config-two-call-work").apply {
            deleteRecursively()
            mkdirs()
        }.absolutePath)

        val results = CHUNK_SIZES.map { chunkSize ->
            runTwoCallTrial(chunkSize = chunkSize, pcmQueueCapacity = PCM_QUEUE_CAPACITY)
        }

        val summary = JSONObject()
            .put("runId", runId)
            .put("integrationPath", "aarHost implementation(files(\"../sdk/build/outputs/aar/sdk-release.aar\"))")
            .put("devicePackage", context.packageName)
            .put("sameEngineWithinEachChunk", true)
            .put("shutdownBetweenChunkTrials", true)
            .put("language", LANGUAGE)
            .put("voiceId", VOICE_ID)
            .put("playType", PlayType.SYNTHESIZE_AND_PLAY.name)
            .put("queueMode", QueueMode.PREEMPT.name)
            .put("pcmQueueCapacity", PCM_QUEUE_CAPACITY)
            .put("firstText", FIRST_TEXT)
            .put("secondText", SECOND_TEXT)
            .put("results", JSONArray(results.map { it.toJson() }))

        File(outputDir, "summary_chunk_50_100.json").writeText(summary.toString(2) + "\n", Charsets.UTF_8)
        File(outputDir, "results_chunk_50_100.csv").writeText(buildCsv(results), Charsets.UTF_8)
        File(outputDir, "TEST_REPORT_ZH.md").writeText(buildReport(summary, results), Charsets.UTF_8)
        Log.i(TAG, "summary=$summary")

        assertTrue("unexpected errors: ${results.flatMap { it.errors }}", results.all { it.errors.isEmpty() })
        assertTrue("missing second first packet", results.all { it.secondFirstPacketMs >= 0L })
        assertTrue(
            "effective chunk mismatch: ${results.map { it.effectiveStreamingChunkSize }}",
            results.zip(CHUNK_SIZES).all { (result, expected) -> result.effectiveStreamingChunkSize == expected },
        )
        assertTrue(
            "effective pcm capacity mismatch: ${results.map { it.effectivePcmQueueCapacity }}",
            results.all { it.effectivePcmQueueCapacity == PCM_QUEUE_CAPACITY },
        )
    }

    private fun runTwoCallTrial(chunkSize: Int, pcmQueueCapacity: Int): TrialResult {
        val createEngineStartMs = System.currentTimeMillis()
        val engine = TextToSpeechSdk.createEngine(
            CreateEngineParams(
                language = LANGUAGE,
                mode = RunMode.OFFLINE,
                voiceId = VOICE_ID,
                engineName = "$runId-chunk-$chunkSize",
            ),
        )
        val createEngineMs = System.currentTimeMillis() - createEngineStartMs

        val listener = TwoCallListener(chunkSize)
        engine.setListener(listener)
        try {
            val firstSubmitAtMs = System.currentTimeMillis()
            engine.speak(FIRST_TEXT, speakParams("chunk-$chunkSize-first-$runId", chunkSize, pcmQueueCapacity))
            assertTrue(
                "chunk=$chunkSize first playback complete timeout",
                listener.firstPlaybackCompleteLatch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS),
            )

            val firstPlaybackCompleteAtMs = listener.firstPlaybackCompleteAtMs
            val secondSubmitAtMs = System.currentTimeMillis()
            engine.speak(SECOND_TEXT, speakParams("chunk-$chunkSize-second-$runId", chunkSize, pcmQueueCapacity))
            assertTrue(
                "chunk=$chunkSize second playback complete timeout",
                listener.secondPlaybackCompleteLatch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS),
            )

            val secondSubmitToStartMs = listener.secondStartAtMs - secondSubmitAtMs
            val middleToSecondFirstPacketMs =
                secondSubmitAtMs + secondSubmitToStartMs + listener.secondFirstPacketMs - firstPlaybackCompleteAtMs

            return TrialResult(
                chunkSize = chunkSize,
                pcmQueueCapacity = pcmQueueCapacity,
                effectiveStreamingChunkSize = listener.secondEffectiveStreamingChunkSize,
                effectivePcmQueueCapacity = listener.secondEffectivePcmQueueCapacity,
                createEngineMs = createEngineMs,
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
            ).also { Log.i(TAG, it.toLogLine()) }
        } finally {
            engine.shutdown()
            Log.i(TAG, "chunk=$chunkSize shutdownCalledAfterTwoCalls=true")
        }
    }

    private fun speakParams(requestId: String, chunkSize: Int, pcmQueueCapacity: Int): SpeakParams =
        SpeakParams(
            requestId = requestId,
            speed = 1.0f,
            playType = PlayType.SYNTHESIZE_AND_PLAY,
            queueMode = QueueMode.PREEMPT,
            languageContext = LANGUAGE,
            streamingConfig = TtsStreamingConfig(
                chunkSize = chunkSize,
                pcmQueueCapacity = pcmQueueCapacity,
            ),
        )

    private fun buildCsv(results: List<TrialResult>): String = buildString {
        appendLine(
            "chunk_size,pcm_queue_capacity,effective_chunk_size,effective_pcm_queue_capacity,create_engine_ms," +
                "first_first_packet_ms,first_submit_to_playback_complete_ms,middle_submit_gap_ms," +
                "second_submit_to_start_ms,second_first_packet_ms,middle_to_second_first_packet_ms," +
                "second_submit_to_playback_complete_ms,errors",
        )
        results.forEach {
            appendCsvLine(
                it.chunkSize.toString(),
                it.pcmQueueCapacity.toString(),
                it.effectiveStreamingChunkSize.toString(),
                it.effectivePcmQueueCapacity.toString(),
                it.createEngineMs.toString(),
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
    }

    private fun buildReport(summary: JSONObject, results: List<TrialResult>): String = buildString {
        appendLine("# Android v3.0 AAR chunk/PCM 接口两次 speak 间隔测试报告")
        appendLine()
        appendLine("## 测试设置")
        appendLine()
        appendLine("- 集成路径：宿主 App `aarHost` 通过 `implementation(files(\"../sdk/build/outputs/aar/sdk-release.aar\"))` 依赖 AAR")
        appendLine("- SDK 接口：`SpeakParams.streamingConfig = TtsStreamingConfig(chunkSize, pcmQueueCapacity)`")
        appendLine("- PCM queue capacity：`${summary.getInt("pcmQueueCapacity")}`")
        appendLine("- 每个 chunk 配置单独创建一个 engine；同一配置内两次 `speak()` 不销毁 engine")
        appendLine("- 流程：句子 1 播放完成回调后立即提交句子 2，记录句子 1 播放完成到句子 2 首包的间隔")
        appendLine()
        appendLine("## 结果")
        appendLine()
        results.forEach {
            appendLine("- chunk `${it.chunkSize}`：生效 chunk `${it.effectiveStreamingChunkSize}`，生效 PCM capacity `${it.effectivePcmQueueCapacity}`；第二句 submit 到首包 `${it.secondFirstPacketMs} ms`；句子 1 播放完成到句子 2 首包 `${it.firstPlaybackCompleteToSecondFirstPacketMs} ms`。")
        }
        appendLine()
        appendLine("## 结论")
        appendLine()
        val fastest = results.minByOrNull { it.firstPlaybackCompleteToSecondFirstPacketMs }
        val slowest = results.maxByOrNull { it.firstPlaybackCompleteToSecondFirstPacketMs }
        if (fastest != null && slowest != null) {
            val diff = slowest.firstPlaybackCompleteToSecondFirstPacketMs - fastest.firstPlaybackCompleteToSecondFirstPacketMs
            appendLine("- 本轮两次 `speak()` 间隔测试中，chunk `${fastest.chunkSize}` 最短，为 `${fastest.firstPlaybackCompleteToSecondFirstPacketMs} ms`；chunk `${slowest.chunkSize}` 最长，为 `${slowest.firstPlaybackCompleteToSecondFirstPacketMs} ms`；差值 `${diff} ms`。")
        }
    }

    private fun StringBuilder.appendCsvLine(vararg cells: String) {
        append(cells.joinToString(",") { it.csvEscape() })
        append('\n')
    }

    private fun String.csvEscape(): String = "\"" + replace("\"", "\"\"") + "\""

    private data class TrialResult(
        val chunkSize: Int,
        val pcmQueueCapacity: Int,
        val effectiveStreamingChunkSize: Int,
        val effectivePcmQueueCapacity: Int,
        val createEngineMs: Long,
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
            .put("chunkSize", chunkSize)
            .put("pcmQueueCapacity", pcmQueueCapacity)
            .put("effectiveStreamingChunkSize", effectiveStreamingChunkSize)
            .put("effectivePcmQueueCapacity", effectivePcmQueueCapacity)
            .put("createEngineMs", createEngineMs)
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
            String.format(
                Locale.US,
                "chunk=%d pcmCapacity=%d effectiveChunk=%d effectivePcmCapacity=%d " +
                    "secondFirstPacketMs=%d middleToSecondFirstPacketMs=%d errors=%s",
                chunkSize,
                pcmQueueCapacity,
                effectiveStreamingChunkSize,
                effectivePcmQueueCapacity,
                secondFirstPacketMs,
                firstPlaybackCompleteToSecondFirstPacketMs,
                errors,
            )
    }

    private class TwoCallListener(private val chunkSize: Int) : SpeakListener {
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

        override fun onStart(requestId: String, response: StartResponse) {
            if (requestId.contains("-first-")) {
                firstStartAtMs = System.currentTimeMillis()
            } else if (requestId.contains("-second-")) {
                secondStartAtMs = System.currentTimeMillis()
                secondEffectiveStreamingChunkSize = response.streamingChunkSize
                secondEffectivePcmQueueCapacity = response.pcmQueueCapacity
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
            errors += "chunk=$chunkSize:$requestId:$errorCode:$errorMessage"
            firstPlaybackCompleteLatch.countDown()
            secondPlaybackCompleteLatch.countDown()
        }
    }

    companion object {
        private const val TAG = "AarChunkTwoCall"
        private const val LANGUAGE = "zh-en"
        private const val VOICE_ID = "lits-female-02"
        private const val PCM_QUEUE_CAPACITY = 128
        private const val TIMEOUT_MS = 60_000L
        private val CHUNK_SIZES = listOf(50, 100)
        private const val FIRST_TEXT = "今天天气很好适合出门散步听音乐放松心情吧"
        private const val SECOND_TEXT = "请稍等片刻系统正在准备新的语音播报内容吧"
    }
}
