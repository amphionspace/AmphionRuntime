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
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * 3.3 号码读法真机契约：含阿拉伯数字号码的句子，必须与其"逐位汉字"写法合成出逐字节相同的 PCM
 * （温度 0，前端 token 相同即输出相同）。旧版把 18912345678 读成"一百八十九亿…"，同一用例会失败。
 * WAV 落到外部文件目录 phone-33/ 供试听与 ASR 旁证。
 */
class PhoneNumberReadingFix33DeviceTest {
    private val cases = listOf(
        Triple("announce", "现在播报号码18912345678。", "现在播报号码幺八九幺二三四五六七八。"),
        Triple("dial", "请拨打18912345678。", "请拨打幺八九幺二三四五六七八。"),
        Triple("badge", "警号123456。", "警号一二三四五六。"),
        Triple("amount", "金额13800138000元。", "金额一百三十八亿零一十三万八千元。"),
    )

    @Test fun numbersReadDigitByDigitMatchTheirHanziSpelling() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val files = context.filesDir
        TextToSpeechSdk.setWorkPath(File(files, "lits-tts-work").absolutePath)
        TextToSpeechSdk.init(context, TtsLicenseOptions(
            license = File(files, "tts-provisioning/amphion-license.lic").readText(),
            licenseAssetName = null,
            deviceIdProvider = TtsDeviceIdProvider { File(files, "tts-provisioning/device-sn.txt").readText().trim() },
        ))
        val outDir = File(context.getExternalFilesDir(null), "phone-33").apply { mkdirs() }
        val report = StringBuilder()
        val results = ArrayList<Triple<String, ByteArray, ByteArray>>()
        val engine = TextToSpeechSdk.createEngine(CreateEngineParams("zh-en", RunMode.OFFLINE, "lits-female-02"))
        try {
            for ((tag, digits, spelled) in cases) {
                val a = synthesize(engine, digits)
                val b = synthesize(engine, spelled)
                writeWav(File(outDir, "$tag-digits.wav"), a)
                writeWav(File(outDir, "$tag-spelled.wav"), b)
                report.append("$tag\t$digits\t${a.size}\t$spelled\t${b.size}\t${if (a.contentEquals(b)) "SAME" else "DIFF"}\n")
                results += Triple("$digits vs $spelled", a, b)
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
        engine.speak(text, SpeakParams("phone-${text.hashCode()}", playType = PlayType.SYNTHESIZE_ONLY))
        assertTrue("timeout: $text", done.await(60, TimeUnit.SECONDS))
        assertEquals("error for $text", null, error)
        return pcm.toByteArray()
    }

    private fun writeWav(file: File, pcm: ByteArray, sampleRate: Int = 24000) {
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
        header.put("RIFF".toByteArray()).putInt(36 + pcm.size).put("WAVE".toByteArray())
        header.put("fmt ".toByteArray()).putInt(16).putShort(1).putShort(1).putInt(sampleRate).putInt(sampleRate * 2).putShort(2).putShort(16)
        header.put("data".toByteArray()).putInt(pcm.size)
        file.outputStream().use { it.write(header.array()); it.write(pcm) }
    }
}
