package com.lits.tts.sdk.internal

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.lits.tts.sdk.*
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class NumericUtteranceDeviceTest {
    @Test
    fun numericChineseTnAndStudentPcm() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val args = InstrumentationRegistry.getArguments()
        val workPath = requireNotNull(args.getString("workPath"))
        val licensePath = requireNotNull(args.getString("licensePath"))
        val serial = requireNotNull(args.getString("deviceSerial"))
        TextToSpeechSdk.init(context, TtsLicenseOptions(
            license = File(licensePath).readText(), licenseAssetName = null,
            deviceIdProvider = TtsDeviceIdProvider { serial },
        ))
        assertEquals(TtsLicenseStatus.State.LICENSED, TextToSpeechSdk.licenseStatus().state)
        TextToSpeechSdk.setWorkPath(workPath)
        val layout = LitsTtsAssetInstaller.ensureInstalled(context, workPath)
        val rows = JSONArray()
        var passed = false
        val report = File(context.filesDir, "numeric-student-report.json")
        try {
            val cases = listOf(
                "0" to "零", "1" to "一", "1." to "一", "2" to "二", "2." to "二",
                "3。" to "三", "4!" to "四", "５。" to "五", "6" to "六", "7" to "七",
                "8" to "八", "9" to "九", "10" to "十", "45." to "四十五",
                "三" to "三", "四" to "四", "五" to "五", "1.5" to "一点五",
            )
            for ((raw, expected) in cases) {
                val normalized = LitsTnNormalizer.normalize(layout, raw, "zh-en", "zh-en")
                val profile = LitsTnNormalizer.lastProfileSummary().orEmpty()
                rows.put(JSONObject().put("text", raw).put("normalized", normalized).put("profile", profile))
                assertTrue("native Chinese TN required: $raw $profile", profile.contains("nativeCalls=zh:"))
                assertEquals(raw, expected, normalized.trim().trimEnd('.', '。', '!', '！', '?', '？'))
                val tokens = LitsTtsFrontend.encode(layout, raw, "zh-en", "zh-en")
                assertTrue("expected initial silence for student inventory", tokens.firstOrNull() == 1L)
            }
            val english = LitsTnNormalizer.normalize(layout, "2.", "en-US", "en-US")
            assertTrue(english.lowercase().contains("two"))
            assertTrue(LitsTnNormalizer.lastProfileSummary().orEmpty().contains("nativeCalls=en:"))
            rows.put(JSONObject().put("english_control", english))
            for ((language, texts) in listOf(
                "zh-en" to listOf("1.", "2", "三四五。", "45。", "你好，世界。"),
                "en-US" to listOf("Hello world."),
            )) {
                val engine = TextToSpeechSdk.createEngine(CreateEngineParams(
                    language = language, mode = RunMode.OFFLINE,
                    voiceId = "lits-female-02",
                ))
                try {
                    for ((index, text) in texts.withIndex()) {
                        val events = Collections.synchronizedList(mutableListOf<String>())
                        val pcm = ByteArrayOutputStream()
                        val done = CountDownLatch(1)
                        val id = "$language-$index"
                        engine.setListener(object : SpeakListener {
                            override fun onStart(requestId: String, response: StartResponse) { events += "start" }
                            override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) {
                                events += "data:${response.sequence}:${audio.size}"
                                pcm.write(audio)
                            }
                            override fun onComplete(requestId: String, response: CompleteResponse) {
                                events += "complete:${response.type}"; done.countDown()
                            }
                            override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
                                events += "error:$errorCode:$errorMessage"; done.countDown()
                            }
                        })
                        engine.speak(text, SpeakParams(requestId = id, languageContext = language,
                            playType = PlayType.SYNTHESIZE_ONLY))
                        assertTrue("timeout for $text", done.await(60, TimeUnit.SECONDS))
                        val trace = synchronized(events) { events.toList() }
                        rows.put(JSONObject().put("synthesis", text).put("events", JSONArray(trace)).put("pcm_bytes", pcm.size()))
                        assertEquals(trace.toString(), "start", trace.firstOrNull())
                        assertEquals(trace.toString(), "complete:${CompleteType.SYNTHESIS_COMPLETE}", trace.lastOrNull())
                        assertEquals(1, trace.count { it == "start" })
                        assertEquals(1, trace.count { it.startsWith("complete:") })
                        val data = trace.drop(1).dropLast(1)
                        assertTrue(trace.toString(), data.isNotEmpty() && data.all { it.startsWith("data:") && it.substringAfterLast(':').toInt() > 0 })
                        assertEquals(data.indices.toList(), data.map { it.split(':')[1].toInt() })
                        File(context.filesDir, "numeric-$id.pcm").writeBytes(pcm.toByteArray())
                    }
                } finally { engine.shutdown() }
            }
            passed = true
        } finally {
            report.writeText(JSONObject().put("pass", passed).put("cases", rows).toString(2))
        }
    }
}
