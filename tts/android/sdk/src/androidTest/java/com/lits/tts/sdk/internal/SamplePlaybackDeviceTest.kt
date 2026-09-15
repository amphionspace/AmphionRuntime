package com.lits.tts.sdk.internal

import android.content.Context
import android.util.Log
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.lits.tts.sdk.*
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.junit.Assert.*
import org.junit.Test

/** Explicit audible smoke test; run only when device playback is requested. */
class SamplePlaybackDeviceTest {
    @Test fun playDifferentSamples() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val args = InstrumentationRegistry.getArguments()
        val serial = requireNotNull(args.getString("deviceSerial"))
        TextToSpeechSdk.init(context, TtsLicenseOptions(
            license = File(requireNotNull(args.getString("licensePath"))).readText(),
            licenseAssetName = null, deviceIdProvider = TtsDeviceIdProvider { serial },
        ))
        TextToSpeechSdk.setWorkPath(requireNotNull(args.getString("workPath")))
        val customText = args.getString("sampleTextPath")?.let { File(it).readText() }
        val groups = if (customText != null) listOf((args.getString("sampleLanguage") ?: "zh-en") to customText.trim().split(Regex("\\n\\s*\\n"))) else listOf(
            "zh-en" to listOf("1.", "2。3。4。5。", "10。45。100。", "1.5。2.75。",
                "你好，欢迎使用语音合成。今天天气不错，我们出去走走吧。",
                "请打开 WiFi，然后点击 OK。Room 204 is ready."),
            "en-US" to listOf("Hello! This is a speech synthesis test. Room two hundred and four is ready."),
        )
        for ((language, samples) in groups) {
            val engine = TextToSpeechSdk.createEngine(CreateEngineParams(language = language,
                mode = RunMode.OFFLINE, voiceId = if (language == "en-US") "lits-female-01" else "lits-female-02"))
            try {
                for ((index, sample) in samples.withIndex()) {
                    val done = CountDownLatch(1)
                    var failure: String? = null
                    var synthesized = false
                    var played = false
                    engine.setListener(object : SpeakListener {
                        override fun onStart(requestId: String, response: StartResponse) {}
                        override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) {}
                        override fun onComplete(requestId: String, response: CompleteResponse) {
                            if (response.type == CompleteType.SYNTHESIS_COMPLETE) synthesized = true
                            if (response.type == CompleteType.PLAYBACK_COMPLETE) { played = true; done.countDown() }
                        }
                        override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
                            failure = "$errorCode:$errorMessage"; done.countDown()
                        }
                    })
                    Log.i("StudentSamplePlayback", "PLAY $language: $sample")
                    engine.speak(sample, SpeakParams(requestId = "play-$language-$index",
                        languageContext = language, playType = PlayType.SYNTHESIZE_AND_PLAY))
                    assertTrue("playback timeout: $sample", done.await(300, TimeUnit.SECONDS))
                    assertNull(failure)
                    assertTrue("synthesis incomplete: $sample", synthesized)
                    assertTrue("playback incomplete: $sample", played)
                    Log.i("StudentSamplePlayback", "COMPLETE $language: $sample")
                    Thread.sleep(800)
                }
            } finally { engine.shutdown() }
        }
    }
}
