package com.lits.tts.sdk.internal

import androidx.test.platform.app.InstrumentationRegistry
import com.lits.tts.sdk.*
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class EnterpriseAuthorizationTest {
    private val ctx = InstrumentationRegistry.getInstrumentation().targetContext
    private val args = InstrumentationRegistry.getArguments()
    private val dir = File(ctx.filesDir, "enterprise-acceptance")
    private val input get() = JSONObject(File(dir, "input.json").readText())
    private fun activate(file: File): Int = try {
        val serial = input.getString("serial")
        TextToSpeechSdk.init(ctx, TtsLicenseOptions(license = file.readText(), licenseAssetName = null, deviceIdProvider = TtsDeviceIdProvider { serial }))
        0
    } catch (error: TextToSpeechException) { error.errorCode }

    @Test fun realSynthesis() {
        val flow = args.getString("flow", "offline")!!
        if (args.getString("requireOffline") == "true") {
            val connectivity = ctx.getSystemService(android.content.Context.CONNECTIVITY_SERVICE) as android.net.ConnectivityManager
            assertNull("offline inference requires no active network", connectivity.activeNetwork)
        }
        var file = File(dir, flow + ".lic")
        if (flow.startsWith("client")) {
            file = File(dir, "client.lic")
            val client = EnterpriseLicenseClient(input.getString("origin"))
            val activation = client.activate(input.getString(flow + "_tts_code"), input.getString("serial"), file)
            if (flow == "client-renew") {
                val old = File(dir, "generation-1.lic").also { file.copyTo(it, overwrite = true) }
                assertEquals(0, activate(old))
                val restored = EnterpriseLicenseClient.Activation(activation.deviceId, activation.token)
                assertEquals(2L, EnterpriseLicenseClient(input.getString("origin")).renew(restored, input.getString("serial"), file))
                assertEquals(0, activate(file))
                assertEquals(TtsErrorCode.LICENSE_MALFORMED, activate(old))
            }
        }
        assertEquals("TTS init authorization", 0, activate(file))
        TextToSpeechSdk.setWorkPath(File(ctx.filesDir, "enterprise-tts-work").absolutePath)
        val engine = TextToSpeechSdk.createEngine(CreateEngineParams(language = "zh-en", mode = RunMode.OFFLINE, voiceId = "lits-female-02"))
        val latch = CountDownLatch(1)
        val pcm = ByteArrayOutputStream()
        var code = 0
        try {
            engine.setListener(object : SpeakListener {
                override fun onStart(requestId: String, response: StartResponse) {}
                override fun onData(requestId: String, data: ByteArray, response: SynthesisResponse) { pcm.write(data) }
                override fun onComplete(requestId: String, response: CompleteResponse) { if (response.type == CompleteType.SYNTHESIS_COMPLETE) latch.countDown() }
                override fun onStop(requestId: String, response: StopResponse) {}
                override fun onError(requestId: String, errorCode: Int, errorMessage: String) { code = errorCode; latch.countDown() }
            })
            if (flow == "expiring") {
                val envelope = JSONObject(file.readText())
                val claims = JSONObject(String(android.util.Base64.decode(envelope.getString("payload_b64"), android.util.Base64.NO_WRAP)))
                val wait = claims.getLong("expiresAtUnix") * 1000 + 500 - System.currentTimeMillis()
                if (wait > 0) Thread.sleep(wait)
            }
            engine.speak("欢迎使用安菲翁语音服务。", SpeakParams(requestId = "enterprise-" + System.nanoTime(), playType = PlayType.SYNTHESIZE_ONLY))
            assertTrue("synthesis timeout", latch.await(120, TimeUnit.SECONDS))
            if (flow == "expiring") {
                assertEquals(TtsErrorCode.LICENSE_EXPIRED, code)
                assertEquals(0, pcm.size())
                File(dir, "tts-expiring-result.json").writeText(JSONObject().put("result", "PASS").put("expiredExistingEngineRejected", true).toString())
                return
            }
            assertEquals("TTS errors", 0, code)
            val bytes = pcm.toByteArray()
            assertTrue("empty audio", bytes.size > 4800)
            assertTrue("silent audio", bytes.any { it.toInt() != 0 })
            File(dir, "tts-" + flow + "-result.json").writeText(JSONObject()
                .put("flow", flow).put("pcmBytes", bytes.size).put("nonSilent", true).put("result", "PASS").toString())
            File(dir, "tts-" + flow + ".pcm").writeBytes(bytes)
        } finally { engine.shutdown() }
    }

    @Test fun parameterMatrix() {
        val cases = input.getJSONArray("tts_cases")
        for (i in 0 until cases.length()) {
            val case = cases.getJSONObject(i)
            assertEquals(case.getString("name"), case.getInt("code"), activate(File(dir, case.getString("file"))))
        }
    }
}
