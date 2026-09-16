package com.lits.tts.sample

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.lits.tts.sdk.*
import java.io.File
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import org.junit.Assert.*
import org.junit.Test

/** Uses the same provisioned files as the sample; no fake synthesizer or native hooks. */
class TtsLifecycleDeviceTest {
    @Test fun cancelAndShutdownDuringRealSynthesisAndPlaybackThenRecover() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val files = context.filesDir
        TextToSpeechSdk.setWorkPath(File(files, "lits-tts-work").absolutePath)
        TextToSpeechSdk.init(context, TtsLicenseOptions(
            license = File(files, "tts-provisioning/amphion-license.lic").readText(),
            licenseAssetName = null,
            deviceIdProvider = TtsDeviceIdProvider { File(files, "tts-provisioning/device-sn.txt").readText().trim() },
        ))
        val events = CopyOnWriteArrayList<String>()
        for ((index, mode) in listOf("stop-playback", "shutdown-synthesis", "shutdown-playback").withIndex()) {
            val engine = createEngine()
            val stopped = CountDownLatch(1)
            val once = AtomicBoolean(false)
            val id = "cancel-$index"
            fun cancel() {
                if (!once.compareAndSet(false, true)) return
                if (mode.startsWith("shutdown")) engine.shutdown() else engine.stop()
            }
            engine.setListener(object : SpeakListener {
                override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) {
                    if (mode == "shutdown-synthesis") cancel()
                }
                override fun onPlaybackStart(requestId: String, elapsedMs: Long) { cancel() }
                override fun onStop(requestId: String, response: StopResponse) {
                    events += "stop:$requestId"
                    stopped.countDown()
                }
                override fun onComplete(requestId: String, response: CompleteResponse) { events += "complete:$requestId" }
                override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
                    events += "error:$requestId:$errorCode:$errorMessage"
                    stopped.countDown()
                }
            })
            engine.speak(SampleTexts.forLanguage("zh-en"), SpeakParams(id,
                playType = if (mode == "shutdown-synthesis") PlayType.SYNTHESIZE_ONLY else PlayType.SYNTHESIZE_AND_PLAY))
            assertTrue(mode, stopped.await(30, TimeUnit.SECONDS))
            if (mode == "stop-playback") engine.shutdown()
            // A new engine must load and complete after cancellation/release; this
            // also leaves ample real work for any late callback to become visible.
            val recovery = createEngine()
            val done = CountDownLatch(1)
            var bytes = 0
            recovery.setListener(object : SpeakListener {
                override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) { bytes += audio.size }
                override fun onComplete(requestId: String, response: CompleteResponse) { done.countDown() }
                override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
                    events += "error:$requestId:$errorCode:$errorMessage"
                    done.countDown()
                }
            })
            try {
                recovery.speak("提示：Hello。恢复测试。", SpeakParams("recovery-$index", playType = PlayType.SYNTHESIZE_ONLY))
                assertTrue(done.await(30, TimeUnit.SECONDS))
                assertTrue("recovery produced PCM", bytes > 0)
                assertEquals(events.toString(), (0..index).map { "stop:cancel-$it" }, events.toList())
            } finally { recovery.shutdown() }
        }
        File(files, "lifecycle-result.txt").writeText("PASS\n" + events.joinToString("\n"))
    }

    private fun createEngine() = TextToSpeechSdk.createEngine(
        CreateEngineParams("zh-en", RunMode.OFFLINE, "lits-female-02"))
}
