package com.lits.tts.sdk.internal

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.lits.tts.sdk.CompleteResponse
import com.lits.tts.sdk.CompleteType
import com.lits.tts.sdk.CreateEngineParams
import com.lits.tts.sdk.PlayType
import com.lits.tts.sdk.RunMode
import com.lits.tts.sdk.SpeakListener
import com.lits.tts.sdk.SpeakParams
import com.lits.tts.sdk.StartResponse
import com.lits.tts.sdk.SynthesisResponse
import com.lits.tts.sdk.TextToSpeechSdk
import com.lits.tts.sdk.TtsLicenseOptions
import java.io.File
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class NegativeTemperatureDeviceTest {
    @Test
    fun nativeFrontendAndPublicSynthesisPreserveTemperatureReading() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val workPath = requireNotNull(InstrumentationRegistry.getArguments().getString("workPath")) {
            "Pass -e workPath pointing to the external TTS model package"
        }
        val layout = LitsTtsAssetInstaller.ensureInstalled(context, workPath)
        val rows = JSONArray()
        val callbacks = Collections.synchronizedList(mutableListOf<String>())
        val reportFile = File(context.filesDir, "temperature-${System.currentTimeMillis()}.json")
        var passed = false
        try {
            listOf(
                "气温-24.5度" to "气温零下二十四点五度",
                "气温 -24.5 度" to "气温零下二十四点五度",
                "温度  -  5 度" to "温度零下五度",
                "体温-0.5度" to "体温零下零点五度",
                "温度范围是-5到10度" to "温度范围是零下五到十度",
                "温度范围是 -5 到 10 度" to "温度范围是零下五到十度",
                "温度范围是  -  5  到  10  度" to "温度范围是零下五到十度",
            ).forEach { (raw, spoken) ->
                val actual = LitsTnNormalizer.normalize(layout, raw, "zh-en", "zh-en")
                val profile = LitsTnNormalizer.lastProfileSummary().orEmpty()
                rows.put(JSONObject().put("raw", raw).put("expected", spoken)
                    .put("normalized", actual).put("profile", profile))
                assertTrue("Native TN must run: $profile", profile.contains("nativeCalls=zh:"))
                assertEquals(raw, spoken, actual)
                assertArrayEquals(raw,
                    LitsTtsFrontend.encodeNormalized(layout, spoken, "zh-en", "zh-en"),
                    LitsTtsFrontend.encode(layout, raw, "zh-en", "zh-en"))
            }

            val license = InstrumentationRegistry.getInstrumentation().context.assets
                .open("lic/tts_only.lic").bufferedReader().use { it.readText() }
            TextToSpeechSdk.init(context, TtsLicenseOptions(license = license))
            TextToSpeechSdk.setWorkPath(workPath)
            val engine = TextToSpeechSdk.createEngine(CreateEngineParams(
                language = "zh-en", mode = RunMode.OFFLINE, voiceId = "lits-female-02",
            ))
            val done = CountDownLatch(1)
            try {
                engine.setListener(object : SpeakListener {
                    override fun onStart(requestId: String, response: StartResponse) {
                        callbacks += "$requestId:start"
                    }
                    override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) {
                        callbacks += "$requestId:data:${response.sequence}:${audio.size}"
                    }
                    override fun onComplete(requestId: String, response: CompleteResponse) {
                        callbacks += "$requestId:complete:${response.type}"
                        done.countDown()
                    }
                    override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
                        callbacks += "$requestId:error:$errorCode:$errorMessage"
                        done.countDown()
                    }
                })
                engine.speak("气温 -24.5 度。温度范围是 -5 到 10 度。", SpeakParams(
                    requestId = "temperature", languageContext = "zh-en", playType = PlayType.SYNTHESIZE_ONLY,
                ))
                assertTrue("Synthesis timeout", done.await(60, TimeUnit.SECONDS))
            } finally {
                engine.shutdown()
            }
            val trace = synchronized(callbacks) { callbacks.toList() }
            assertEquals("temperature:start", trace.firstOrNull())
            assertEquals("temperature:complete:${CompleteType.SYNTHESIS_COMPLETE}", trace.lastOrNull())
            assertEquals(1, trace.count { it == "temperature:start" })
            assertEquals(1, trace.count { it.startsWith("temperature:complete:") })
            val data = trace.drop(1).dropLast(1)
            assertTrue("Expected PCM callbacks: $trace", data.isNotEmpty())
            assertTrue("Unexpected callback or empty PCM: $trace", data.all {
                it.startsWith("temperature:data:") && it.substringAfterLast(':').toInt() > 0
            })
            passed = true
        } finally {
            reportFile.writeText(JSONObject().put("pass", passed).put("cases", rows)
                .put("callbacks", JSONArray(synchronized(callbacks) { callbacks.toList() })).toString(2))
        }
    }
}
