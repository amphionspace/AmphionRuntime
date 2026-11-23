package com.lits.tts.sample

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.lits.tts.sdk.CompleteResponse
import com.lits.tts.sdk.CreateEngineParams
import com.lits.tts.sdk.PlayType
import com.lits.tts.sdk.RunMode
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
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * 3.3 读音修复真机契约：模型温度为 0、前端 token 序列相同时输出确定，所以"南站"（修复后 nan2）必须与
 * 同音写法"难站"合成出逐字节相同的 PCM；"重做 / 重试"（chong2）与"虫做 / 虫试"同理。
 * 每条合成结果先落盘为 WAV（外部文件目录 pronunciation-33/），再做断言，便于用旧版本包跑同一用例留证。
 */
class PronunciationFix33DeviceTest {
    private val cases = listOf(
        Triple("nanzhan", "成都南站到了。", "成都难站到了。"),
        Triple("chongzuo", "请重做一次。", "请虫做一次。"),
        Triple("chongshi", "正在重试。", "正在虫试。"),
    )

    @Test fun fixedWordsSynthesiseTheSameAudioAsTheirHomophones() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val files = context.filesDir
        TextToSpeechSdk.setWorkPath(File(files, "lits-tts-work").absolutePath)
        TextToSpeechSdk.init(context, TtsLicenseOptions(
            license = File(files, "tts-provisioning/amphion-license.lic").readText(),
            licenseAssetName = null,
            deviceIdProvider = TtsDeviceIdProvider { File(files, "tts-provisioning/device-sn.txt").readText().trim() },
        ))
        val outDir = File(context.getExternalFilesDir(null), "pronunciation-33").apply { mkdirs() }
        val report = StringBuilder()
        val results = ArrayList<Triple<String, ByteArray, ByteArray>>()
        val engine = TextToSpeechSdk.createEngine(CreateEngineParams("zh-en", RunMode.OFFLINE, "lits-female-02"))
        try {
            for ((tag, fixed, homophone) in cases) {
                val a = synthesize(engine, fixed)
                val b = synthesize(engine, homophone)
                writeWav(File(outDir, "$tag-fixed.wav"), a)
                writeWav(File(outDir, "$tag-homophone.wav"), b)
                report.append("$tag\t$fixed\t${a.size}\t${sha(a)}\t$homophone\t${b.size}\t${sha(b)}\t${if (a.contentEquals(b)) "SAME" else "DIFF"}\n")
                results += Triple("$fixed vs $homophone", a, b)
            }
        } finally {
            engine.shutdown()
            File(outDir, "report.tsv").writeText(report.toString())
        }
        for ((label, a, b) in results) {
            assertTrue("$label: non-empty PCM", a.isNotEmpty())
            assertEquals("$label: PCM must be identical", b.size, a.size)
            assertTrue("$label: PCM bytes differ", a.contentEquals(b))
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
        engine.speak(text, SpeakParams("pron-${text.hashCode()}", playType = PlayType.SYNTHESIZE_ONLY))
        assertTrue("timeout: $text", done.await(60, TimeUnit.SECONDS))
        assertEquals("error for $text", null, error)
        return pcm.toByteArray()
    }

    private fun sha(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

    /** 16-bit mono PCM at the SDK's 24 kHz output rate. */
    private fun writeWav(file: File, pcm: ByteArray, sampleRate: Int = 24000) {
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
        header.put("RIFF".toByteArray()).putInt(36 + pcm.size).put("WAVE".toByteArray())
        header.put("fmt ".toByteArray()).putInt(16).putShort(1).putShort(1).putInt(sampleRate).putInt(sampleRate * 2).putShort(2).putShort(16)
        header.put("data".toByteArray()).putInt(pcm.size)
        file.outputStream().use { it.write(header.array()); it.write(pcm) }
    }
}
