package com.lits.tts.sdk.internal

import android.content.Context
import android.util.Log
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.lits.tts.sdk.*
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean
import org.json.JSONObject
import org.json.JSONArray
import org.junit.Assert.*
import org.junit.Test

class ZeroTemperatureSamplesDeviceTest {
    @Test fun playVariedSamples() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val args = InstrumentationRegistry.getArguments()
        TextToSpeechSdk.init(context, TtsLicenseOptions(
            license = File(requireNotNull(args.getString("licensePath"))).readText(),
            licenseAssetName = null, deviceIdProvider = TtsDeviceIdProvider { requireNotNull(args.getString("deviceSerial")) },
        ))
        val cases = listOf(
            Triple("zh-en", 1, "1。2。3。4。5。10。45。100。"),
            Triple("zh-en", 1, "1.5。2.75。今天的温度是二十五点六度。"),
            Triple("zh-en", 1, "你好，欢迎使用语音合成。今天天气不错，我们出去走走吧。"),
            Triple("zh-en", 1, "请把白色背包放在旁边，再帮我拿一瓶冰水。"),
            Triple("zh-en", 1, "你现在方便接电话吗？好的，我十分钟后再联系你。"),
            Triple("zh-en", 1, "清晨的阳光照进窗户，桌上的茶还冒着热气。我打开电脑，整理好今天需要完成的事情，然后戴上耳机，认真听完这段语音。希望每一句都清楚自然，句子之间的停顿也恰到好处。"),
            Triple("zh-en", 1, "请打开 WiFi，然后点击 OK。Room 204 is ready."),
            Triple("en-US", 0, "Hello! This is a speech synthesis test. Room two hundred and four is ready."),
            Triple("en-US", 0, "Please put the blue backpack beside the table, then bring me a bottle of cold water."),
            Triple("en-US", 0, "Good morning. Before we begin, please check your microphone and make sure the room is quiet. When you are ready, read the next sentence slowly and clearly. Thank you for your help.")
        )
        val workPath = requireNotNull(args.getString("workPath"))
        val manifest = File(workPath, "tts/dingqiao_intmeanflow_student_0010000_vocos24k/0.1.0/manifest.json")
        assertEquals(0.0, JSONObject(manifest.readText()).getDouble("inference_temperature"), 0.0)
        var synth: LitsDeliveryPcmSynthesizer? = null
        var currentSpeaker = -1
        val player = AndroidPcmPlayer()
        val results = JSONArray()
        try {
            for ((index, sample) in cases.withIndex()) {
                val i = index + 1
                val (language, speaker, text) = sample
                if (speaker != currentSpeaker) {
                    synth?.close()
                    synth = LitsDeliveryPcmSynthesizer(context, workPath, speaker)
                    synth!!.preload()
                    currentSpeaker = speaker
                }
                val params = CreateEngineParams(language = language, mode = RunMode.OFFLINE,
                    voiceId = if (speaker == 0) "lits-female-01" else "lits-female-02")
                val audio = synth!!.synthesize(text, SpeakParams(requestId = "zero-varied-$i", languageContext = language, speed = 1.0f), params)
                assertEquals(24000, audio.sampleRate)
                assertTrue(audio.pcm.isNotEmpty())
                File(context.filesDir, "zero-varied-$i.pcm").writeBytes(audio.pcm)
                val digest = MessageDigest.getInstance("SHA-256").digest(audio.pcm).joinToString("") { "%02x".format(it) }
                Log.i("ZeroTemperatureSamples", "PLAY $i: $text sha256=$digest")
                player.playBlocking(audio, AtomicBoolean(false), null)
                Log.i("ZeroTemperatureSamples", "COMPLETE $i")
                results.put(JSONObject().put("round", i).put("text", text).put("language", language).put("speaker", speaker).put("pcmBytes", audio.pcm.size).put("sha256", digest))
                Thread.sleep(1200)
            }
            File(context.filesDir, "zero-varied-report.json").writeText(JSONObject().put("pass", true).put("temperature", 0.0)
                .put("model", synth!!.debugSummary()).put("sampleRate", 24000).put("rounds", results).toString(2))
        } finally { player.stop(); synth?.close() }
    }
}
