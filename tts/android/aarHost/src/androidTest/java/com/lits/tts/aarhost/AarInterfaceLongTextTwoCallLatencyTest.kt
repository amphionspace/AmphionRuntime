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
import org.junit.Assert.assertTrue
import org.junit.Test

class AarInterfaceLongTextTwoCallLatencyTest {
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()
    private val outputDir = File(
        context.getExternalFilesDir(null) ?: context.filesDir,
        "aar-long-text-two-call-latency",
    ).apply { mkdirs() }
    private val runId = "aar-long-text-two-call-${System.currentTimeMillis()}"

    @Test
    fun twoLongTextsMeasureSpeakToSpeakLatencyForChunk50And100() {
        assertTrue("first text must exceed 100 chars", FIRST_TEXT.length > 100)
        assertTrue("second text must exceed 100 chars", SECOND_TEXT.length > 100)

        TextToSpeechSdk.setWorkPath(File(context.cacheDir, "aar-long-text-two-call-work").apply {
            deleteRecursively()
            mkdirs()
        }.absolutePath)

        val results = CHUNK_CONFIGS.map { config ->
            runTwoCallTrial(config = config, pcmQueueCapacity = PCM_QUEUE_CAPACITY)
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
            .put("firstTextLength", FIRST_TEXT.length)
            .put("secondTextLength", SECOND_TEXT.length)
            .put("firstText", FIRST_TEXT)
            .put("secondText", SECOND_TEXT)
            .put("results", JSONArray(results.map { it.toJson() }))

        File(outputDir, "summary_long_text_chunk_50_100.json").writeText(summary.toString(2) + "\n", Charsets.UTF_8)
        File(outputDir, "results_long_text_chunk_50_100.csv").writeText(buildCsv(results), Charsets.UTF_8)
        File(outputDir, "TEST_REPORT_ZH.md").writeText(buildReport(summary, results), Charsets.UTF_8)
        Log.i(TAG, "summary=$summary")

        assertTrue("unexpected errors: ${results.flatMap { it.errors }}", results.all { it.errors.isEmpty() })
        assertTrue("missing second first packet", results.all { it.secondFirstPacketMs >= 0L })
        assertTrue(
            "effective chunk mismatch: ${results.map { it.effectiveStreamingChunkSize }}",
            results.zip(CHUNK_CONFIGS).all { (result, expected) -> result.effectiveStreamingChunkSize == expected.chunkSize },
        )
        assertTrue(
            "effective pcm capacity mismatch: ${results.map { it.effectivePcmQueueCapacity }}",
            results.all { it.effectivePcmQueueCapacity == PCM_QUEUE_CAPACITY },
        )
    }

    private fun runTwoCallTrial(config: ChunkConfig, pcmQueueCapacity: Int): TrialResult {
        val createEngineStartMs = System.currentTimeMillis()
        val engine = TextToSpeechSdk.createEngine(
            CreateEngineParams(
                language = LANGUAGE,
                mode = RunMode.OFFLINE,
                voiceId = VOICE_ID,
                engineName = "$runId-chunk-${config.chunkSize}-first-${config.firstChunkSize}",
            ),
        )
        val createEngineMs = System.currentTimeMillis() - createEngineStartMs

        val listener = TwoCallListener(config)
        engine.setListener(listener)
        try {
            val firstSubmitAtMs = System.currentTimeMillis()
            engine.speak(FIRST_TEXT, speakParams("${config.caseId}-call1-$runId", config, pcmQueueCapacity))
            assertTrue(
                "${config.caseId} first playback complete timeout",
                listener.firstPlaybackCompleteLatch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS),
            )

            val firstPlaybackCompleteAtMs = listener.firstPlaybackCompleteAtMs
            val secondSubmitAtMs = System.currentTimeMillis()
            engine.speak(SECOND_TEXT, speakParams("${config.caseId}-call2-$runId", config, pcmQueueCapacity))
            assertTrue(
                "${config.caseId} second playback complete timeout",
                listener.secondPlaybackCompleteLatch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS),
            )

            val secondSubmitToStartMs = listener.secondStartAtMs - secondSubmitAtMs
            val middleToSecondFirstPacketMs =
                secondSubmitAtMs + secondSubmitToStartMs + listener.secondFirstPacketMs - firstPlaybackCompleteAtMs

            return TrialResult(
                caseId = config.caseId,
                chunkSize = config.chunkSize,
                firstChunkSize = config.firstChunkSize,
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
                firstProfilingInfo = listener.firstProfilingInfo,
                secondProfilingInfo = listener.secondProfilingInfo,
                secondPlaybackStartMs = listener.secondPlaybackStartMs,
                firstPlaybackCompleteToSecondFirstPacketMs = middleToSecondFirstPacketMs,
                secondSubmitToPlaybackCompleteMs = listener.secondPlaybackCompleteAtMs - secondSubmitAtMs,
                errors = listener.errors.toList(),
            ).also { Log.i(TAG, it.toLogLine()) }
        } finally {
            engine.shutdown()
            Log.i(TAG, "${config.caseId} shutdownCalledAfterLongTextTwoCalls=true")
        }
    }

    private fun speakParams(requestId: String, config: ChunkConfig, pcmQueueCapacity: Int): SpeakParams =
        SpeakParams(
            requestId = requestId,
            speed = 1.0f,
            playType = PlayType.SYNTHESIZE_AND_PLAY,
            queueMode = QueueMode.PREEMPT,
            languageContext = LANGUAGE,
            streamingConfig = TtsStreamingConfig(
                chunkSize = config.chunkSize,
                firstChunkSize = config.firstChunkSize,
                pcmQueueCapacity = pcmQueueCapacity,
            ),
        )

    private fun buildCsv(results: List<TrialResult>): String = buildString {
        appendLine(
            "case_id,chunk_size,pcm_queue_capacity,effective_chunk_size,effective_pcm_queue_capacity,create_engine_ms," +
                "first_chunk_size," +
                "first_first_packet_ms,first_synthesis_ms,first_audio_duration_ms,first_submit_to_playback_complete_ms," +
                "middle_submit_gap_ms,second_submit_to_start_ms,second_first_packet_ms,second_synthesis_ms," +
                "second_audio_duration_ms,second_playback_start_ms,middle_to_second_first_packet_ms," +
                "second_submit_to_playback_complete_ms,first_profiling_info,second_profiling_info,errors",
        )
        results.forEach {
            appendCsvLine(
                it.caseId,
                it.chunkSize.toString(),
                it.pcmQueueCapacity.toString(),
                it.effectiveStreamingChunkSize.toString(),
                it.effectivePcmQueueCapacity.toString(),
                it.createEngineMs.toString(),
                it.firstChunkSize.toString(),
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
                it.firstPlaybackCompleteToSecondFirstPacketMs.toString(),
                it.secondSubmitToPlaybackCompleteMs.toString(),
                it.firstProfilingInfo,
                it.secondProfilingInfo,
                it.errors.joinToString("; "),
            )
        }
    }

    private fun buildReport(summary: JSONObject, results: List<TrialResult>): String = buildString {
        appendLine("# Android v3.0 AAR 长文本两次 speak 间隔测试报告")
        appendLine()
        appendLine("## 测试设置")
        appendLine()
        appendLine("- 集成路径：宿主 App `aarHost` 通过 `implementation(files(\"../sdk/build/outputs/aar/sdk-release.aar\"))` 依赖 AAR")
        appendLine("- SDK 接口：`SpeakParams.streamingConfig = TtsStreamingConfig(chunkSize, pcmQueueCapacity)`")
        appendLine("- 文本长度：第一段 `${summary.getInt("firstTextLength")}` 字，第二段 `${summary.getInt("secondTextLength")}` 字")
        appendLine("- PCM queue capacity：`${summary.getInt("pcmQueueCapacity")}`")
        appendLine("- 每个 chunk 配置单独创建一个 engine；同一配置内两次 `speak()` 不销毁 engine")
        appendLine("- 流程：长文本 1 播放完成回调后立即提交长文本 2，记录长文本 1 播放完成到长文本 2 首包的间隔")
        appendLine()
        appendLine("## 结果")
        appendLine()
        results.forEach {
            appendLine("- `${it.caseId}`：生效 chunk `${it.effectiveStreamingChunkSize}`，生效 PCM capacity `${it.effectivePcmQueueCapacity}`；第二段 submit 到首包 `${it.secondFirstPacketMs} ms`；长文本 1 播放完成到长文本 2 首包 `${it.firstPlaybackCompleteToSecondFirstPacketMs} ms`；第二段听到首写入 `${it.secondPlaybackStartMs} ms`；第二段音频时长 `${it.secondAudioDurationMs} ms`。")
            appendLine("  - 第二段 profiling：`${it.secondProfilingInfo}`")
        }
    }

    private fun StringBuilder.appendCsvLine(vararg cells: String) {
        append(cells.joinToString(",") { it.csvEscape() })
        append('\n')
    }

    private fun String.csvEscape(): String = "\"" + replace("\"", "\"\"") + "\""

    private data class ChunkConfig(val chunkSize: Int, val firstChunkSize: Int) {
        val caseId: String = "chunk-$chunkSize-first-$firstChunkSize"
    }

    private data class TrialResult(
        val caseId: String,
        val chunkSize: Int,
        val firstChunkSize: Int,
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
        val firstProfilingInfo: String,
        val secondProfilingInfo: String,
        val secondPlaybackStartMs: Long,
        val firstPlaybackCompleteToSecondFirstPacketMs: Long,
        val secondSubmitToPlaybackCompleteMs: Long,
        val errors: List<String>,
    ) {
        fun toJson(): JSONObject = JSONObject()
            .put("caseId", caseId)
            .put("chunkSize", chunkSize)
            .put("firstChunkSize", firstChunkSize)
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
            .put("firstProfilingInfo", firstProfilingInfo)
            .put("secondProfilingInfo", secondProfilingInfo)
            .put("secondPlaybackStartMs", secondPlaybackStartMs)
            .put("firstPlaybackCompleteToSecondFirstPacketMs", firstPlaybackCompleteToSecondFirstPacketMs)
            .put("secondSubmitToPlaybackCompleteMs", secondSubmitToPlaybackCompleteMs)
            .put("errors", JSONArray(errors))

        fun toLogLine(): String =
            String.format(
                Locale.US,
                "case=%s chunk=%d firstChunk=%d pcmCapacity=%d effectiveChunk=%d effectivePcmCapacity=%d " +
                    "secondFirstPacketMs=%d middleToSecondFirstPacketMs=%d secondPlaybackStartMs=%d secondAudioDurationMs=%d secondProfiling=%s errors=%s",
                caseId,
                chunkSize,
                firstChunkSize,
                pcmQueueCapacity,
                effectiveStreamingChunkSize,
                effectivePcmQueueCapacity,
                secondFirstPacketMs,
                firstPlaybackCompleteToSecondFirstPacketMs,
                secondPlaybackStartMs,
                secondAudioDurationMs,
                secondProfilingInfo,
                errors,
            )
    }

    private class TwoCallListener(private val config: ChunkConfig) : SpeakListener {
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
            errors += "${config.caseId}:$requestId:$errorCode:$errorMessage"
            firstPlaybackCompleteLatch.countDown()
            secondPlaybackCompleteLatch.countDown()
        }
    }

    companion object {
        private const val TAG = "AarLongTwoCall"
        private const val LANGUAGE = "zh-en"
        private const val VOICE_ID = "lits-female-02"
        private const val PCM_QUEUE_CAPACITY = 128
        private const val TIMEOUT_MS = 240_000L
        private val CHUNK_CONFIGS = listOf(
            ChunkConfig(chunkSize = 50, firstChunkSize = 50),
            ChunkConfig(chunkSize = 100, firstChunkSize = 100),
            ChunkConfig(chunkSize = 100, firstChunkSize = 50),
        )
        private const val FIRST_TEXT =
            "第一段长文本用于测试安卓三点零AAR接口在真实手机上的连续调用表现。" +
                "今天我们模拟导航播报、系统提醒和应用内语音提示同时出现的场景，观察第一段完整播放结束之后，第二次调用speak是否能够立即进入队列并快速产生首包音频，避免用户感知到明显停顿。"
        private const val SECOND_TEXT =
            "第二段长文本继续覆盖超过一百字的输入长度，并保持相同的说话人、播放类型和队列策略。" +
                "这段内容包含会议提醒、天气变化、路线信息和后台任务完成提示，用来确认长文本合成完成之后再次调用speak时，SDK不会重新初始化引擎，也不会因为缓存或播放线程切换造成额外等待。"
    }
}
