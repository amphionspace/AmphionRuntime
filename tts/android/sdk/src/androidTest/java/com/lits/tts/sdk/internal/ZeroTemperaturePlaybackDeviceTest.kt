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

class ZeroTemperaturePlaybackDeviceTest {
    @Test fun repeatEnglish() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val args = InstrumentationRegistry.getArguments()
        TextToSpeechSdk.init(context, TtsLicenseOptions(
            license = File(requireNotNull(args.getString("licensePath"))).readText(),
            licenseAssetName = null, deviceIdProvider = TtsDeviceIdProvider { requireNotNull(args.getString("deviceSerial")) },
        ))
        val text = "Hello! This is a speech synthesis test. Room two hundred and four is ready."
        val params = CreateEngineParams(language = "en-US", mode = RunMode.OFFLINE, voiceId = "lits-female-01")
        val workPath = requireNotNull(args.getString("workPath"))
        val manifest = File(workPath, "tts/dingqiao_intmeanflow_student_0010000_vocos24k/0.1.0/manifest.json")
        assertEquals(0.0, JSONObject(manifest.readText()).getDouble("inference_temperature"), 0.0)
        val synth = LitsDeliveryPcmSynthesizer(context, workPath, 0)
        val player = AndroidPcmPlayer()
        val results = JSONArray()
        try {
            synth.preload()
            assertTrue(synth.debugSummary(), synth.debugSummary().contains("dingqiao_intmeanflow_student_0010000"))
            for (i in 1..8) {
                val audio = synth.synthesize(text, SpeakParams(requestId = "zero-$i", languageContext = "en-US", speed = 1.0f), params)
                assertEquals(24000, audio.sampleRate)
                assertTrue(audio.pcm.isNotEmpty())
                File(context.filesDir, "zero-$i.pcm").writeBytes(audio.pcm)
                val digest = MessageDigest.getInstance("SHA-256").digest(audio.pcm).joinToString("") { "%02x".format(it) }
                Log.i("ZeroTemperature", "PLAY $i sha256=$digest")
                player.playBlocking(audio, AtomicBoolean(false), null)
                Log.i("ZeroTemperature", "COMPLETE $i")
                results.put(JSONObject().put("round", i).put("pcmBytes", audio.pcm.size).put("sha256", digest))
                Thread.sleep(800)
            }
            File(context.filesDir, "zero-report.json").writeText(JSONObject().put("pass", true).put("temperature", 0.0)
                .put("model", synth.debugSummary()).put("text", text).put("sampleRate", 24000).put("rounds", results).toString(2))
        } finally { player.stop(); synth.close() }
    }
}
