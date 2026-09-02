package com.amphion.dingqiao.demo

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.AudioInfo
import com.amphion.dingqiao.DINGQIAO_SPEAKER_MODEL_FILENAME
import com.amphion.dingqiao.SpeechRecognizeSdk
import com.amphion.dingqiao.VoiceprintRegisterParams
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.PI
import kotlin.math.sin
import org.junit.After
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class DingqiaoEmbeddedVoiceprintModelInstrumentedTest {

    @After
    fun releaseRuntime() {
        SpeechRecognizeSdk.unloadRuntime()
    }

    @Test
    fun embeddedSpeakerModel_installsAndRegistersVoiceprint() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val workDir = File(context.filesDir, "dingqiao_embedded_voiceprint_test").apply {
            deleteRecursively()
            mkdirs()
        }
        val model = File(workDir, DINGQIAO_SPEAKER_MODEL_FILENAME)
        assertFalse("test must start without external speaker model", model.exists())

        prepareSdkRuntime(context, workDir)

        assertTrue(
            "preloadVoiceprintModel should install the embedded model",
            SpeechRecognizeSdk.preloadVoiceprintModel(),
        )
        assertTrue("embedded speaker model should be installed to workPath", model.isFile)
        assertTrue("embedded speaker model should be readable", model.canRead())
        assertTrue("embedded speaker model looks too small: ${model.length()}", model.length() > MIN_MODEL_BYTES)

        val sample = File(workDir, "voiceprint_sample.wav")
        sample.writeBytes(sineWav(durationSec = 4))

        val result = SpeechRecognizeSdk.registerVoiceprint(
            VoiceprintRegisterParams(
                samplePaths = listOf(sample.absolutePath),
                audioInfo = AudioInfo(),
            ),
        )
        val id = result.voiceprintId.keys.firstOrNull()
        assertTrue("voiceprint id should be returned", !id.isNullOrBlank())
        assertTrue("voiceprint should be persisted", File(workDir, "voiceprints/$id/embedding.bin").isFile)
    }

    private fun sineWav(durationSec: Int): ByteArray {
        val samples = SAMPLE_RATE * durationSec
        val dataBytes = samples * 2
        val out = ByteBuffer.allocate(44 + dataBytes).order(ByteOrder.LITTLE_ENDIAN)
        out.put("RIFF".toByteArray(Charsets.US_ASCII))
        out.putInt(36 + dataBytes)
        out.put("WAVE".toByteArray(Charsets.US_ASCII))
        out.put("fmt ".toByteArray(Charsets.US_ASCII))
        out.putInt(16)
        out.putShort(1)
        out.putShort(1)
        out.putInt(SAMPLE_RATE)
        out.putInt(SAMPLE_RATE * 2)
        out.putShort(2)
        out.putShort(16)
        out.put("data".toByteArray(Charsets.US_ASCII))
        out.putInt(dataBytes)
        for (i in 0 until samples) {
            val t = i.toDouble() / SAMPLE_RATE
            val v = (sin(2.0 * PI * 220.0 * t) * 12000).toInt().toShort()
            out.putShort(v)
        }
        return out.array()
    }

    private companion object {
        private const val SAMPLE_RATE = 16_000
        private const val MIN_MODEL_BYTES = 30L * 1024L * 1024L
    }
}
