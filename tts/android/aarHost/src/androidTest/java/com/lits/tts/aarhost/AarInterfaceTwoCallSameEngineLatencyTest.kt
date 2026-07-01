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
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AarInterfaceTwoCallSameEngineLatencyTest {
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()
    private val outputDir = File(
        context.getExternalFilesDir(null) ?: context.filesDir,
        "aar-two-call-same-engine-latency",
    ).apply { mkdirs() }
    private val runId = "aar-two-call-same-engine-${System.currentTimeMillis()}"

    @Test
    fun twoTwentyCharSentencesUseSameAarEngineWithoutDestroying() {
        assertEquals(20, FIRST_TEXT.length)
        assertEquals(20, SECOND_TEXT.length)

        TextToSpeechSdk.setWorkPath(File(context.cacheDir, "aar-two-call-work").apply {
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

        val listener = TwoCallListener()
        engine.setListener(listener)
        try {
            val firstSubmitAtMs = System.currentTimeMillis()
            engine.speak(FIRST_TEXT, speakParams("first-$runId"))
            assertTrue("first playback complete timeout", listener.firstPlaybackCompleteLatch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS))

            val firstPlaybackCompleteAtMs = listener.firstPlaybackCompleteAtMs
            val secondSubmitAtMs = System.currentTimeMillis()
            engine.speak(SECOND_TEXT, speakParams("second-$runId"))
            assertTrue("second playback complete timeout", listener.secondPlaybackCompleteLatch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS))

            val result = JSONObject()
                .put("runId", runId)
                .put("integrationPath", "aarHost implementation(files(\"../sdk/build/outputs/aar/sdk-debug.aar\"))")
                .put("devicePackage", context.packageName)
                .put("sameEngine", true)
                .put("shutdownBetweenCalls", false)
                .put("language", LANGUAGE)
                .put("voiceId", VOICE_ID)
                .put("playType", PlayType.SYNTHESIZE_AND_PLAY.name)
                .put("queueMode", QueueMode.PREEMPT.name)
                .put("createEngineMs", createEngineMs)
                .put("firstText", FIRST_TEXT)
                .put("firstTextLength", FIRST_TEXT.length)
                .put("secondText", SECOND_TEXT)
                .put("secondTextLength", SECOND_TEXT.length)
                .put("firstSubmitToStartMs", listener.firstStartAtMs - firstSubmitAtMs)
                .put("firstFirstPacketMs", listener.firstFirstPacketMs)
                .put("firstSynthesisMs", listener.firstSynthesisMs)
                .put("firstAudioDurationMs", listener.firstAudioDurationMs)
                .put("firstSubmitToPlaybackCompleteMs", firstPlaybackCompleteAtMs - firstSubmitAtMs)
                .put("firstPlaybackCompleteToSecondSubmitMs", secondSubmitAtMs - firstPlaybackCompleteAtMs)
                .put("secondSubmitToStartMs", listener.secondStartAtMs - secondSubmitAtMs)
                .put("secondFirstPacketMs", listener.secondFirstPacketMs)
                .put("secondSynthesisMs", listener.secondSynthesisMs)
                .put("secondAudioDurationMs", listener.secondAudioDurationMs)
                .put("secondSubmitToPlaybackCompleteMs", listener.secondPlaybackCompleteAtMs - secondSubmitAtMs)
                .put(
                    "firstPlaybackCompleteToSecondFirstPacketMs",
                    secondSubmitAtMs + listener.secondFirstPacketMs - firstPlaybackCompleteAtMs,
                )
                .put("errors", listener.errors)

            File(outputDir, "summary.json").writeText(result.toString(2) + "\n", Charsets.UTF_8)
            File(outputDir, "TEST_REPORT_ZH.md").writeText(buildReport(result), Charsets.UTF_8)
            Log.i(TAG, "result=${result}")

            assertTrue("unexpected errors: ${listener.errors}", listener.errors.isEmpty())
            assertTrue("second first packet missing", listener.secondFirstPacketMs >= 0L)
        } finally {
            engine.shutdown()
            Log.i(TAG, "shutdownCalledAfterBothCalls=true")
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

    private fun buildReport(result: JSONObject): String = buildString {
        appendLine("# Android v2.5.4 AAR 同引擎两次调用时延测试报告")
        appendLine()
        appendLine("## 测试设置")
        appendLine()
        appendLine("- 集成路径：宿主 App `aarHost` 通过 `implementation(files(\"../sdk/build/outputs/aar/sdk-debug.aar\"))` 依赖 AAR")
        appendLine("- 引擎策略：只创建一次 engine，两次 `speak()` 中间不销毁引擎")
        appendLine("- 流程：句子 1 `SYNTHESIZE_AND_PLAY` 播放完成回调后，立即提交句子 2")
        appendLine("- 句子 1：`${result.getString("firstText")}`，长度 `${result.getInt("firstTextLength")}`")
        appendLine("- 句子 2：`${result.getString("secondText")}`，长度 `${result.getInt("secondTextLength")}`")
        appendLine()
        appendLine("## 关键结果")
        appendLine()
        appendLine("- `createEngine` 耗时：`${result.getLong("createEngineMs")} ms`")
        appendLine("- 句子 1 submit 到首包：`${result.getLong("firstFirstPacketMs")} ms`")
        appendLine("- 句子 1 submit 到播放完成：`${result.getLong("firstSubmitToPlaybackCompleteMs")} ms`")
        appendLine("- 句子 1 播放完成到句子 2 submit：`${result.getLong("firstPlaybackCompleteToSecondSubmitMs")} ms`")
        appendLine("- 句子 2 submit 到 `onStart`：`${result.getLong("secondSubmitToStartMs")} ms`")
        appendLine("- 句子 2 submit 到首包：`${result.getLong("secondFirstPacketMs")} ms`")
        appendLine("- 句子 1 播放完成到句子 2 首包：`${result.getLong("firstPlaybackCompleteToSecondFirstPacketMs")} ms`")
        appendLine("- 句子 2 submit 到播放完成：`${result.getLong("secondSubmitToPlaybackCompleteMs")} ms`")
        appendLine()
        appendLine("## 结论")
        appendLine()
        val middle = result.getLong("firstPlaybackCompleteToSecondFirstPacketMs")
        val approx = String.format(Locale.US, "%.2f", middle / 1000.0)
        appendLine("- 本轮同 engine、两次 AAR 接口调用的中间首包间隔约 `${approx}s`。")
    }

    private class TwoCallListener : SpeakListener {
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
            if (requestId.startsWith("first-")) {
                firstStartAtMs = System.currentTimeMillis()
            } else if (requestId.startsWith("second-")) {
                secondStartAtMs = System.currentTimeMillis()
            }
        }

        override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) = Unit

        override fun onComplete(requestId: String, response: CompleteResponse) {
            if (response.type == CompleteType.SYNTHESIS_COMPLETE) {
                if (requestId.startsWith("first-")) {
                    firstFirstPacketMs = response.firstPacketMs
                    firstSynthesisMs = response.synthesisMs
                    firstAudioDurationMs = response.audioDurationMs
                } else if (requestId.startsWith("second-")) {
                    secondFirstPacketMs = response.firstPacketMs
                    secondSynthesisMs = response.synthesisMs
                    secondAudioDurationMs = response.audioDurationMs
                }
            } else if (response.type == CompleteType.PLAYBACK_COMPLETE) {
                if (requestId.startsWith("first-")) {
                    firstPlaybackCompleteAtMs = System.currentTimeMillis()
                    firstPlaybackCompleteLatch.countDown()
                } else if (requestId.startsWith("second-")) {
                    secondPlaybackCompleteAtMs = System.currentTimeMillis()
                    secondPlaybackCompleteLatch.countDown()
                }
            }
        }

        override fun onStop(requestId: String, response: StopResponse) = Unit

        override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
            errors += "$requestId:$errorCode:$errorMessage"
            firstPlaybackCompleteLatch.countDown()
            secondPlaybackCompleteLatch.countDown()
        }
    }

    companion object {
        private const val TAG = "AarTwoCallLatency"
        private const val LANGUAGE = "zh-en"
        private const val VOICE_ID = "lits-female-02"
        private const val TIMEOUT_MS = 60_000L
        private const val FIRST_TEXT = "今天天气很好适合出门散步听音乐放松心情吧"
        private const val SECOND_TEXT = "请稍等片刻系统正在准备新的语音播报内容吧"
    }
}
