package com.lits.tts.sdk.internal

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.lits.tts.sdk.*
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class ColonPunctuationDeviceTest {
    @Test
    fun sentenceColonUsesPunctuationThroughNativeTnAndStreamingSdk() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val args = InstrumentationRegistry.getArguments()
        val workPath = requireNotNull(args.getString("workPath"))
        TextToSpeechSdk.init(context, TtsLicenseOptions(
            license = File(requireNotNull(args.getString("licensePath"))).readText(),
            licenseAssetName = null,
            deviceIdProvider = TtsDeviceIdProvider { requireNotNull(args.getString("deviceSerial")) },
        ))
        TextToSpeechSdk.setWorkPath(workPath)
        val layout = LitsTtsAssetInstaller.ensureInstalled(context, workPath)
        val rows = JSONArray()
        for (colon in listOf(":", "：")) {
            for (suffix in listOf("Hello", "Room 204 is ready.", "The meeting starts at nine thirty.")) {
                val raw = "提示${colon}${suffix}"
                val spaced = "提示${colon} ${suffix}"
                val tn = LitsTnNormalizer.normalize(layout, raw, "zh-en", "zh-en")
                val profile = LitsTnNormalizer.lastProfileSummary().orEmpty()
                assertTrue(profile, profile.contains("nativeCalls=zh:"))
                assertFalse("$raw -> $tn", tn.contains("冒号"))
                assertArrayEquals(raw,
                    LitsTtsFrontend.encode(layout, spaced, "zh-en", "zh-en"),
                    LitsTtsFrontend.encode(layout, raw, "zh-en", "zh-en"))
                rows.put(JSONObject().put("text", raw).put("normalized", tn).put("profile", profile))
            }
        }
        val time = LitsTnNormalizer.normalize(layout, "会议时间：9:30", "zh-en", "zh-en")
        assertTrue(time, time.contains("九点三十分"))
        assertFalse(time, time.contains("冒号"))
        val url = LitsTnNormalizer.normalize(layout, "请访问https://example.com", "zh-en", "zh-en")
        assertTrue(url, url.contains("冒号斜杠斜杠"))
        val engine = TextToSpeechSdk.createEngine(CreateEngineParams(
            language = "zh-en", mode = RunMode.OFFLINE, voiceId = "lits-female-02"))
        var bytes = 0
        var streaming = false
        var failure: String? = null
        val done = CountDownLatch(1)
        try {
            engine.setListener(object : SpeakListener {
                override fun onStart(requestId: String, response: StartResponse) {
                    streaming = response.isStreaming
                }
                override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) {
                    bytes += audio.size
                }
                override fun onComplete(requestId: String, response: CompleteResponse) {
                    if (response.type == CompleteType.SYNTHESIS_COMPLETE) done.countDown()
                }
                override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
                    failure = "$errorCode:$errorMessage"
                    done.countDown()
                }
            })
            engine.speak("屏幕上显示：The meeting starts at nine thirty.", SpeakParams(
                requestId = "colon-regression", languageContext = "zh-en", playType = PlayType.SYNTHESIZE_ONLY))
            assertTrue("synthesis timeout", done.await(90, TimeUnit.SECONDS))
            assertNull(failure)
            assertTrue("streaming model required", streaming)
            assertTrue("nonempty audio required", bytes > 0)
            File(context.filesDir, "colon-report.json").writeText(JSONObject()
                .put("pass", true).put("cases", rows).put("time", time).put("url", url)
                .put("streaming", streaming).put("pcmBytes", bytes).toString(2))
        } finally {
            engine.shutdown()
        }
    }
}
