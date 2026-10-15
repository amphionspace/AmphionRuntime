package com.amphion.dingqiao.demo

import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.*
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/** Inputs are issued by the live control plane and staged outside the APK. */
class EnterpriseAuthorizationTest {
    private val ctx = InstrumentationRegistry.getInstrumentation().targetContext
    private val args = InstrumentationRegistry.getArguments()
    private val dir = File(ctx.filesDir, "enterprise-acceptance")
    private val input get() = JSONObject(File(dir, "input.json").readText())
    private fun initialize() {
        val serial = input.getString("serial")
        SpeechRecognizeSdk.init(ctx, LicenseDeviceIdProvider { serial })
        SpeechRecognizeSdk.setWorkPath(File(ctx.filesDir, "enterprise-work").absolutePath)
    }
    private fun activate(file: File): Int {
        val latch = CountDownLatch(1)
        var code = -1
        SpeechRecognizeSdk.setLicense(file.absolutePath, object : LicenseActivationCallback {
            override fun onResult(result: LicenseActivationResult) { code = result.errorCode; latch.countDown() }
            override fun onError(errorCode: Int, errorMessage: String) { code = errorCode; latch.countDown() }
        })
        assertTrue("activation timeout", latch.await(30, TimeUnit.SECONDS))
        return code
    }

    @Test fun realRecognition() {
        initialize()
        val flow = args.getString("flow", "offline")!!
        if (args.getString("requireOffline") == "true") {
            val connectivity = ctx.getSystemService(android.content.Context.CONNECTIVITY_SERVICE) as android.net.ConnectivityManager
            assertNull("offline inference requires no active network", connectivity.activeNetwork)
        }
        var file = File(dir, flow + ".lic")
        if (flow.startsWith("client")) {
            file = File(dir, "client.lic")
            val client = EnterpriseLicenseClient(input.getString("origin"))
            val activation = client.activate(input.getString(flow + "_code"), input.getString("serial"), file)
            if (flow == "client-renew") {
                val old = File(dir, "generation-1.lic").also { file.copyTo(it, overwrite = true) }
                assertEquals(0, activate(old))
                val restored = EnterpriseLicenseClient.Activation(activation.deviceId, activation.token)
                assertEquals(2L, EnterpriseLicenseClient(input.getString("origin")).renew(restored, input.getString("serial"), file))
                assertEquals(0, activate(file))
                assertEquals(DingqiaoErrorCode.LICENSE_INVALID, activate(old))
            }
        }
        assertEquals("setLicense", 0, activate(file))
        val ready = CountDownLatch(1)
        var prepareCode = -1
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() { prepareCode = 0; ready.countDown() }
            override fun onError(errorCode: Int, errorMessage: String) { prepareCode = errorCode; ready.countDown() }
        })
        assertTrue("prepare timeout", ready.await(120, TimeUnit.SECONDS))
        assertEquals("prepareRuntime", 0, prepareCode)
        val engine = SpeechRecognizeSdk.createEngine(CreateEngineParams(language = "zh-CN", online = DingqiaoOnlineMode.OFFLINE))
        val listener = CapturingListener()
        try {
            engine.setListener(listener)
            val sid = "enterprise-" + System.nanoTime()
            engine.startListening(StartParams(sid, AudioInfo(), extraParams = mapOf("enablePartialResult" to true)))
            assertTrue("start timeout", listener.awaitStarted(15000))
            if (flow == "expiring") {
                val envelope = JSONObject(file.readText())
                val claims = JSONObject(String(android.util.Base64.decode(envelope.getString("payload_b64"), android.util.Base64.NO_WRAP)))
                val wait = claims.getLong("expiresAtUnix") * 1000 + 500 - System.currentTimeMillis()
                if (wait > 0) Thread.sleep(wait)
                engine.writeAudio(sid, ByteArray(DQ_FRAME))
                assertTrue("expiry error timeout", listener.awaitError(15000))
                assertEquals(listOf(DingqiaoErrorCode.LICENSE_EXPIRED), listener.errorCodes())
                assertTrue(listener.finals.isEmpty())
                assertTrue(listener.completes.isEmpty())
                File(dir, "asr-expiring-result.json").writeText(JSONObject().put("result", "PASS").put("expiredRunningSessionRejected", true).toString())
                return
            }
            val pcm = DqWav.read16kMonoPcm("input.wav", File(dir, "input.wav").readBytes())
            feedFrames(engine, sid, pcm, 20)
            feedSilence(engine, sid, 800)
            engine.finish(sid)
            assertTrue("recognition timeout", listener.awaitComplete(60000))
            assertTrue("ASR error codes: ${listener.errorCodes()}", listener.errors.isEmpty())
            assertTrue("empty ASR result", listener.finalText().isNotBlank())
            assertEquals(1, listener.finals.count { it.isLast })
            assertEquals(1, listener.completes.size)
            File(dir, "asr-" + flow + "-result.json").writeText(JSONObject()
                .put("flow", flow).put("textCharacters", listener.finalText().length).put("nonEmptyText", true).put("finals", listener.finals.size)
                .put("last", 1).put("complete", 1).put("result", "PASS").toString())
        } finally { engine.shutdown() }
    }

    @Test fun parameterMatrix() {
        initialize()
        val cases = input.getJSONArray("asr_cases")
        for (i in 0 until cases.length()) {
            val case = cases.getJSONObject(i)
            assertEquals(case.getString("name"), case.getInt("code"), activate(File(dir, case.getString("file"))))
        }
    }
}
