package com.lits.tts.sample

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.lits.tts.sdk.CompleteResponse
import com.lits.tts.sdk.CreateEngineParams
import com.lits.tts.sdk.RunMode
import com.lits.tts.sdk.PlayType
import com.lits.tts.sdk.SpeakListener
import com.lits.tts.sdk.SpeakParams
import com.lits.tts.sdk.SynthesisResponse
import com.lits.tts.sdk.TextToSpeechSdk
import com.lits.tts.sdk.TtsDeviceIdProvider
import com.lits.tts.sdk.TtsLicenseOptions
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * 缺陷 #94 真机契约：句末标点贴着下一句（"ready?Yes"）与带空格写法（"ready? Yes"）必须合成出
 * 完全相同的 PCM——模型温度为 0、前端 token 序列相同时输出确定。使用与 Demo 相同的授权与内置资源。
 */
class GluedPunctuationDeviceTest {
    @Test fun gluedSentencePunctuationSynthesisesTheSameAudioAsSpaced() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val files = context.filesDir
        TextToSpeechSdk.setWorkPath(File(files, "lits-tts-work").absolutePath)
        TextToSpeechSdk.init(context, TtsLicenseOptions(
            license = File(files, "tts-provisioning/amphion-license.lic").readText(),
            licenseAssetName = null,
            deviceIdProvider = TtsDeviceIdProvider { File(files, "tts-provisioning/device-sn.txt").readText().trim() },
        ))
        val cases = listOf(
            "en-US" to ("Are you ready?Yes, I am." to "Are you ready? Yes, I am."),
            "en-US" to ("Are you ready.Yes I am." to "Are you ready. Yes I am."),
            "en-US" to ("Ready...Yes" to "Ready... Yes"),
            "zh-en" to ("你好吗?好的" to "你好吗? 好的"),
        )
        for ((language, pair) in cases) {
            val engine = TextToSpeechSdk.createEngine(CreateEngineParams(language, RunMode.OFFLINE, "lits-female-02"))
            try {
                val glued = synthesize(engine, pair.first)
                val spaced = synthesize(engine, pair.second)
                assertTrue("${pair.first}: non-empty PCM", glued.isNotEmpty())
                assertEquals("${pair.first} vs ${pair.second}: PCM must be identical", spaced.size, glued.size)
                assertTrue("${pair.first} vs ${pair.second}: PCM bytes differ", spaced.contentEquals(glued))
            } finally {
                engine.shutdown()
            }
        }
    }

    private fun synthesize(engine: com.lits.tts.sdk.TextToSpeechEngine, text: String): ByteArray {
        val pcm = ByteArrayOutputStream()
        val done = CountDownLatch(1)
        var error: String? = null
        engine.setListener(object : SpeakListener {
            override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) { pcm.write(audio) }
            override fun onComplete(requestId: String, response: CompleteResponse) { done.countDown() }
            override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
                error = "$errorCode:$errorMessage"; done.countDown()
            }
        })
        engine.speak(text, SpeakParams("glued-${text.hashCode()}", playType = PlayType.SYNTHESIZE_ONLY))
        assertTrue("timeout: $text", done.await(60, TimeUnit.SECONDS))
        assertEquals("error for $text", null, error)
        return pcm.toByteArray()
    }
}
