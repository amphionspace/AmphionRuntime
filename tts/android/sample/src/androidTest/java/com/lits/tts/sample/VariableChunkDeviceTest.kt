package com.lits.tts.sample

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.lits.tts.sdk.*
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/** Public SDK test with the provisioned model: requested chunk sizes must reach inference. */
class VariableChunkDeviceTest {
    @Test fun cachedInferenceAcceptsDifferentChunkSizes() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val files = context.filesDir
        TextToSpeechSdk.setWorkPath(File(files, "lits-tts-work").absolutePath)
        TextToSpeechSdk.init(context, TtsLicenseOptions(
            license = File(files, "tts-provisioning/amphion-license.lic").readText(),
            licenseAssetName = null,
            deviceIdProvider = TtsDeviceIdProvider { File(files, "tts-provisioning/device-sn.txt").readText().trim() },
        ))
        val engine = TextToSpeechSdk.createEngine(CreateEngineParams("zh-en", RunMode.OFFLINE, "lits-female-02"))
        val rows = JSONArray()
        val text = "计算机视觉的未来，还有许多值得探索的问题。我们从图像出发，理解世界，也学习如何与世界交互。Hello, welcome to the future of computer vision."
        var expectedBytes: Int? = null
        try {
            for (size in listOf(50, 100, 75, 150)) {
                val done = CountDownLatch(1)
                val pcm = ByteArrayOutputStream()
                var start: StartResponse? = null
                var complete: CompleteResponse? = null
                var error: String? = null
                var chunks = 0
                var allStreaming = true
                engine.setListener(object : SpeakListener {
                    override fun onStart(requestId: String, response: StartResponse) { start = response }
                    override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) {
                        allStreaming = allStreaming && response.isStreaming && response.chunkSource == "model_stream" && response.sequence == chunks
                        chunks++
                        pcm.write(audio)
                    }
                    override fun onComplete(requestId: String, response: CompleteResponse) {
                        complete = response
                        done.countDown()
                    }
                    override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
                        error = "$errorCode:$errorMessage"
                        done.countDown()
                    }
                })
                engine.speak(text, SpeakParams("chunk-$size", playType = PlayType.SYNTHESIZE_ONLY,
                    streamingConfig = TtsStreamingConfig(chunkSize = size)))
                assertTrue("chunk=$size timed out", done.await(90, TimeUnit.SECONDS))
                assertNull("chunk=$size", error)
                assertEquals(size, start?.streamingChunkSize)
                assertEquals("model_stream_callback", start?.dataPath)
                assertEquals(CompleteType.SYNTHESIS_COMPLETE, complete?.type)
                assertTrue(allStreaming)
                assertTrue("cross-chunk output", chunks > 1)
                assertTrue(pcm.size() > 0)
                if (expectedBytes == null) expectedBytes = pcm.size() else assertEquals(expectedBytes, pcm.size())
                File(files, "variable-chunk-$size.pcm").writeBytes(pcm.toByteArray())
                rows.put(JSONObject().put("chunkSize", size).put("chunks", chunks).put("pcmBytes", pcm.size())
                    .put("firstPacketMs", complete!!.firstPacketMs).put("synthesisMs", complete!!.synthesisMs)
                    .put("audioDurationMs", complete!!.audioDurationMs).put("profile", complete!!.profilingInfo))
            }
        } finally { engine.shutdown() }
        File(files, "variable-chunk-result.json").writeText(JSONObject().put("text", text).put("cases", rows).toString(2))
    }
}
