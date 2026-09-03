package com.lits.tts.aarhost

import android.app.Activity
import android.content.Intent
import android.os.SystemClock
import androidx.test.platform.app.InstrumentationRegistry
import com.lits.tts.sdk.CompleteResponse
import com.lits.tts.sdk.CompleteType
import com.lits.tts.sdk.CreateEngineParams
import com.lits.tts.sdk.PlayType
import com.lits.tts.sdk.RunMode
import com.lits.tts.sdk.SpeakListener
import com.lits.tts.sdk.SpeakParams
import com.lits.tts.sdk.StartResponse
import com.lits.tts.sdk.StopResponse
import com.lits.tts.sdk.SynthesisResponse
import com.lits.tts.sdk.TextToSpeechSdk
import com.lits.tts.sdk.TtsLicenseOptions
import com.lits.tts.sdk.TtsLicenseStatus
import java.io.File
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Public API only: aarHost depends on sdk-release.aar, never the SDK project or internal classes. */
class AarFrontendContractDeviceTest {
    @Test
    fun licensedExternalModelsProduceOrderedPcm() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val arguments = InstrumentationRegistry.getArguments()
        val workPath = requireNotNull(arguments.getString("workPath")) { "Pass -e workPath <external model root>" }
        val licensePath = requireNotNull(arguments.getString("licensePath")) { "Pass -e licensePath <private license file>" }
        val prefix = "这是一段用于验证流式分段的中文测试文本".repeat(3).take(49)
        val text = "气温 -24.5 度。温度范围是 -5 到 10 度。出生日期1998年2月09日。${prefix}example.com/test。下一句。"
        val requestId = "aar-frontend"
        val startedAt = SystemClock.elapsedRealtime()
        val callbacks = Collections.synchronizedList(mutableListOf<JSONObject>())
        val reportFile = File(context.filesDir, "aar-frontend-${System.currentTimeMillis()}.json")
        val report = JSONObject().put("pass", false).put("text", text).put("requestId", requestId)
            .put("language", "zh-en").put("voiceId", "lits-female-02").put("playType", "SYNTHESIZE_ONLY")
        var activity: Activity? = null
        fun event(id: String, type: String) = JSONObject().put("requestId", id).put("type", type)
            .put("elapsedMs", SystemClock.elapsedRealtime() - startedAt)
        try {
            activity = instrumentation.startActivitySync(Intent(context, AarHostActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            // Caller-owned assets are read in place: never clear or replace workPath.
            TextToSpeechSdk.init(context, TtsLicenseOptions(license = File(licensePath).readText(), licenseAssetName = null))
            val licenseState = TextToSpeechSdk.licenseStatus().state
            report.put("licenseState", licenseState.name)
            assertEquals("Unarmed/development builds cannot pass this gate", TtsLicenseStatus.State.LICENSED, licenseState)
            TextToSpeechSdk.setWorkPath(workPath)
            val engine = TextToSpeechSdk.createEngine(CreateEngineParams(
                language = "zh-en", mode = RunMode.OFFLINE, voiceId = "lits-female-02",
            ))
            val done = CountDownLatch(1)
            try {
                engine.setListener(object : SpeakListener {
                    override fun onStart(requestId: String, response: StartResponse) {
                        callbacks += event(requestId, "start").put("audioType", response.audioType)
                            .put("sampleRate", response.sampleRate).put("sampleBit", response.sampleBit)
                            .put("audioChannel", response.audioChannel)
                    }
                    override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) {
                        callbacks += event(requestId, "data").put("sequence", response.sequence)
                            .put("bytes", audio.size).put("audioType", response.audioType)
                    }
                    override fun onComplete(requestId: String, response: CompleteResponse) {
                        callbacks += event(requestId, "complete").put("completeType", response.type.name)
                        done.countDown()
                    }
                    override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
                        callbacks += event(requestId, "error").put("errorCode", errorCode).put("message", errorMessage)
                        done.countDown()
                    }
                    override fun onStop(requestId: String, response: StopResponse) {
                        callbacks += event(requestId, "stop").put("stopType", response.type.name)
                        done.countDown()
                    }
                })
                engine.speak(text, SpeakParams(requestId = requestId, languageContext = "zh-en", playType = PlayType.SYNTHESIZE_ONLY))
                assertTrue("Synthesis timeout; see $reportFile", done.await(60, TimeUnit.SECONDS))
            } finally {
                engine.shutdown()
                report.put("shutdownReturned", true)
            }
            val trace = synchronized(callbacks) { callbacks.toList() }
            assertTrue("All callbacks belong to this request: $trace", trace.all { it.getString("requestId") == requestId })
            assertEquals("start", trace.firstOrNull()?.getString("type"))
            assertEquals("complete", trace.lastOrNull()?.getString("type"))
            assertEquals(1, trace.count { it.getString("type") == "start" })
            assertEquals(1, trace.count { it.getString("type") == "complete" })
            assertEquals(CompleteType.SYNTHESIS_COMPLETE.name, trace.last().getString("completeType"))
            val start = trace.first()
            assertEquals("pcm", start.getString("audioType"))
            assertEquals(24000, start.getInt("sampleRate"))
            assertEquals(16, start.getInt("sampleBit"))
            assertEquals(1, start.getInt("audioChannel"))
            val data = trace.drop(1).dropLast(1)
            assertTrue("Expected PCM callbacks: $trace", data.isNotEmpty())
            assertTrue("Unexpected callback or invalid PCM: $trace", data.all {
                it.getString("type") == "data" && it.getString("audioType") == "pcm" &&
                    it.getInt("bytes") > 0 && it.getInt("bytes") % 2 == 0
            })
            assertEquals("PCM sequence must be contiguous and ordered", data.indices.toList(), data.map { it.getInt("sequence") })
            report.put("pass", true)
        } finally {
            try {
                report.put("elapsedMs", SystemClock.elapsedRealtime() - startedAt)
                    .put("callbacks", JSONArray(synchronized(callbacks) { callbacks.toList() }))
                reportFile.writeText(report.toString(2))
                println("AAR_FRONTEND_REPORT=${reportFile.absolutePath}")
            } finally {
                instrumentation.runOnMainSync { activity?.finish() }
            }
        }
    }
}
