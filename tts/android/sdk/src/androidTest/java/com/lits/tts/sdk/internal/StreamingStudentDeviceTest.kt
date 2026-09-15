package com.lits.tts.sdk.internal

import android.content.Context
import android.util.Log
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.lits.tts.sdk.*
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/** Explicitly provisioned streaming integration test; playback is opt-in. */
class StreamingStudentDeviceTest {
    @Test fun synthesizeAndOptionallyPlay() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val args = InstrumentationRegistry.getArguments()
        TextToSpeechSdk.init(context, TtsLicenseOptions(
            license = File(requireNotNull(args.getString("licensePath"))).readText(),
            licenseAssetName = null,
            deviceIdProvider = TtsDeviceIdProvider { requireNotNull(args.getString("deviceSerial")) },
        ))
        TextToSpeechSdk.setWorkPath(requireNotNull(args.getString("workPath")))
        val rows = JSONArray()
        val groups = listOf(
            "zh-en" to listOf("1。2。45。1.5。", "你好，欢迎使用语音合成。", "清晨的阳光照进窗户桌上的茶还冒着热气我打开电脑整理好今天需要完成的事情然后戴上耳机认真听完这段语音。"),
            "en-US" to listOf("Hello! This is a speech synthesis test. Room two hundred and four is ready.", "Please put the blue backpack beside the table, then bring me a bottle of cold water.", "Good morning. Before we begin, please check your microphone and make sure the room is quiet. When you are ready, read the next sentence slowly and clearly. Thank you for your help."),
        )
        run {
            for ((language, samples) in groups) {
                val engine = TextToSpeechSdk.createEngine(CreateEngineParams(language = language,
                    mode = RunMode.OFFLINE, voiceId = if (language == "en-US") "lits-female-01" else "lits-female-02"))
                try {
                    for (text in samples) {
                        val index = rows.length() + 1
                        val pcm = ByteArrayOutputStream()
                        val times = JSONArray()
                        val done = CountDownLatch(1)
                        val started = System.nanoTime()
                        var error: String? = null
                        var streaming = false
                        var profile = ""
                        var firstMs = -1L
                        var synthesisMs = -1L
                        var model = ""
                        var callbacksStreaming = true
                        engine.setListener(object : SpeakListener {
                            override fun onStart(requestId: String, response: StartResponse) {
                                streaming = response.isStreaming
                                model = response.modelInfo
                            }
                            override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) {
                                pcm.write(audio)
                                callbacksStreaming = callbacksStreaming && response.isStreaming
                                times.put((System.nanoTime() - started) / 1_000_000)
                            }
                            override fun onComplete(requestId: String, response: CompleteResponse) {
                                if (response.type == CompleteType.SYNTHESIS_COMPLETE) {
                                    profile = response.profilingInfo
                                    firstMs = response.firstPacketMs
                                    synthesisMs = response.synthesisMs
                                    done.countDown()
                                }
                            }
                            override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
                                error = "$errorCode:$errorMessage"; done.countDown()
                            }
                        })
                        engine.speak(text, SpeakParams(requestId = "streaming-$index", languageContext = language,
                            playType = PlayType.SYNTHESIZE_ONLY))
                        assertTrue("timeout", done.await(180, TimeUnit.SECONDS))
                        assertNull(error)
                        assertTrue(model, model.contains("student_0010000_streaming"))
                        assertTrue("streaming start required", streaming)
                        assertTrue("streaming callbacks required", callbacksStreaming)
                        assertTrue("nonempty audio", pcm.size() > 0)
                        assertTrue(profile, profile.contains("intmeanflow_absolute_kv"))
                        if (text.length > 60) {
                            assertTrue("multiple real chunks required", times.length() > 1)
                            assertTrue("first packet must precede synthesis completion", firstMs >= 0 && firstMs < synthesisMs)
                        }
                        File(context.filesDir, "streaming-$index.pcm").writeBytes(pcm.toByteArray())
                        rows.put(JSONObject().put("index", index).put("text", text).put("language", language)
                            .put("pcmBytes", pcm.size()).put("chunkTimesMs", times).put("firstPacketMs", firstMs)
                            .put("synthesisMs", synthesisMs).put("profile", profile).put("model", model))
                        File(context.filesDir, "streaming-report.json").writeText(JSONObject().put("pass", false).put("cases", rows).toString(2))
                        if (args.getString("playAudio") == "true") {
                            Log.i("StreamingStudent", "PLAY $index: $text")
                            val played = CountDownLatch(1)
                            var playbackError: String? = null
                            var directStream = false
                            var synthComplete = false
                            engine.setListener(object : SpeakListener {
                                override fun onStart(requestId: String, response: StartResponse) {
                                    directStream = response.isStreaming && response.dataPath == "model_stream_playback"
                                }
                                override fun onComplete(requestId: String, response: CompleteResponse) {
                                    if (response.type == CompleteType.SYNTHESIS_COMPLETE) synthComplete = true
                                    if (response.type == CompleteType.PLAYBACK_COMPLETE) played.countDown()
                                }
                                override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
                                    playbackError = "$errorCode:$errorMessage"; played.countDown()
                                }
                            })
                            engine.speak(text, SpeakParams(requestId = "streaming-play-$index", languageContext = language,
                                playType = PlayType.SYNTHESIZE_AND_PLAY))
                            assertTrue("direct playback timeout", played.await(180, TimeUnit.SECONDS))
                            assertNull(playbackError)
                            assertTrue("direct streaming playback required", directStream)
                            assertTrue("direct synthesis complete required", synthComplete)
                        }
                        Log.i("StreamingStudent", "COMPLETE $index chunks=${times.length()} firstMs=$firstMs synthesisMs=$synthesisMs")
                    }
                } finally { engine.shutdown() }
            }
            File(context.filesDir, "streaming-report.json").writeText(JSONObject().put("pass", true).put("cases", rows).toString(2))
        }
    }
}
