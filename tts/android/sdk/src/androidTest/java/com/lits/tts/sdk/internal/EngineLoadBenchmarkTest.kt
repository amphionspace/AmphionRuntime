package com.lits.tts.sdk.internal

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
import com.lits.tts.sdk.TextToSpeechSdk
import com.lits.tts.sdk.TtsStreamingConfig
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Test

class EngineLoadBenchmarkTest {
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()

    @Test
    fun measureColdZhEngineLoad() {
        val outputDir = File(context.getExternalFilesDir(null) ?: context.filesDir, "engine-load-benchmark").apply { mkdirs() }
        val workDir = File(context.filesDir, "engine-load-benchmark-work").apply {
            deleteRecursively()
            mkdirs()
        }
        TextToSpeechSdk.setWorkPath(workDir.absolutePath)

        val createStartedAt = System.currentTimeMillis()
        val engine = TextToSpeechSdk.createEngine(
            CreateEngineParams(
                language = "zh-en",
                mode = RunMode.OFFLINE,
                voiceId = "lits-female-02",
                engineName = "engine-load-${System.nanoTime()}",
            ),
        )
        val createEngineMs = System.currentTimeMillis() - createStartedAt

        val done = CountDownLatch(1)
        var startResponse: StartResponse? = null
        var completeResponse: CompleteResponse? = null
        var errorMessage: String? = null
        var bytes = 0L
        engine.setListener(
            object : SpeakListener {
                override fun onStart(requestId: String, response: StartResponse) {
                    startResponse = response
                }

                override fun onData(requestId: String, audio: ByteArray, response: com.lits.tts.sdk.SynthesisResponse) {
                    bytes += audio.size
                }

                override fun onComplete(requestId: String, response: CompleteResponse) {
                    if (response.type == CompleteType.SYNTHESIS_COMPLETE) {
                        completeResponse = response
                        done.countDown()
                    }
                }

                override fun onError(requestId: String, errorCode: Int, errorMessageText: String) {
                    errorMessage = "$errorCode:$errorMessageText"
                    done.countDown()
                }
            },
        )
        engine.speak(
            "引擎加载速度测试，room 204 is ready.",
            SpeakParams(
                requestId = "engine-load-${System.nanoTime()}",
                playType = PlayType.SYNTHESIZE_ONLY,
                queueMode = QueueMode.PREEMPT,
                languageContext = "zh-en",
                streamingConfig = TtsStreamingConfig(chunkSize = 50, pcmQueueCapacity = 128),
            ),
        )
        assertTrue(errorMessage ?: "timeout", done.await(90, TimeUnit.SECONDS))
        engine.shutdown()

        val result = JSONObject()
            .put("createEngineMs", createEngineMs)
            .put("bytes", bytes)
            .put("error", errorMessage ?: JSONObject.NULL)
            .put("modelInfo", startResponse?.modelInfo ?: JSONObject.NULL)
            .put("loadProfileInfo", startResponse?.loadProfileInfo ?: JSONObject.NULL)
            .put("firstPacketMs", completeResponse?.firstPacketMs ?: JSONObject.NULL)
            .put("synthesisMs", completeResponse?.synthesisMs ?: JSONObject.NULL)
            .put("profilingInfo", completeResponse?.profilingInfo ?: JSONObject.NULL)
            .put("workPath", workDir.absolutePath)
        File(outputDir, "engine-load-benchmark-summary.json").writeText(result.toString(2) + "\n")
        assertTrue("expected synthesized bytes, result=$result", bytes > 0)
    }
}
