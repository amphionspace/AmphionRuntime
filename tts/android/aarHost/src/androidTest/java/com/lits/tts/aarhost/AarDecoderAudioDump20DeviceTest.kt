package com.lits.tts.aarhost

import android.os.SystemClock
import android.util.Log
import androidx.test.core.app.ApplicationProvider
import com.lits.tts.sdk.CompleteResponse
import com.lits.tts.sdk.CompleteType
import com.lits.tts.sdk.CreateEngineParams
import com.lits.tts.sdk.PlayType
import com.lits.tts.sdk.QueueMode
import com.lits.tts.sdk.RunMode
import com.lits.tts.sdk.SpeakListener
import com.lits.tts.sdk.SpeakParams
import com.lits.tts.sdk.StartResponse
import com.lits.tts.sdk.StopResponse
import com.lits.tts.sdk.SynthesisResponse
import com.lits.tts.sdk.TextToSpeechEngine
import com.lits.tts.sdk.TextToSpeechSdk
import com.lits.tts.sdk.TtsStreamingConfig
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AarDecoderAudioDump20DeviceTest {
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()
    private val variant = instrumentationArg("variant") ?: "decoder"
    private val runId = "$variant-${System.currentTimeMillis()}"
    private val outputDir = File(
        context.getExternalFilesDir(null) ?: context.filesDir,
        "decoder-audio-dump-20/$variant-$runId",
    ).apply { mkdirs() }

    @Test
    fun synthesizeTwentyShortTextsAndSaveWavs() {
        val workPath = instrumentationArg("workPath")
            ?: File(context.cacheDir, "decoder-audio-dump-work").absolutePath
        TextToSpeechSdk.setWorkPath(File(workPath).apply { mkdirs() }.absolutePath)

        val engine = TextToSpeechSdk.createEngine(
            CreateEngineParams(
                language = LANGUAGE,
                mode = RunMode.OFFLINE,
                voiceId = VOICE_ID,
                engineName = runId,
            ),
        )
        val results = mutableListOf<AudioDumpResult>()
        try {
            runWarmup(engine)
            TEST_TEXTS.forEachIndexed { index, text ->
                val result = runSpeak(engine, index, text)
                results += result
                Log.i(TAG, "variant=$variant result=${result.toJson().toCompactString()}")
                Thread.sleep(INTER_SPEAK_SLEEP_MS)
            }
        } finally {
            runCatching { engine.shutdown() }
        }

        val summary = JSONObject()
            .put("runId", runId)
            .put("variant", variant)
            .put("devicePackage", context.packageName)
            .put("integrationPath", "aarHost implementation(files(\"../sdk/build/outputs/aar/sdk-release.aar\"))")
            .put("workPath", workPath)
            .put("language", LANGUAGE)
            .put("voiceId", VOICE_ID)
            .put("playType", PlayType.SYNTHESIZE_ONLY.name)
            .put("queueMode", QueueMode.PREEMPT.name)
            .put("chunkSize", CHUNK_SIZE)
            .put("firstChunkSize", FIRST_CHUNK_SIZE)
            .put("textCount", TEST_TEXTS.size)
            .put("results", JSONArray(results.map { it.toJson() }))
        File(outputDir, "summary-$runId.json").writeText(summary.toString(2) + "\n", Charsets.UTF_8)

        assertEquals("audio dump result count", TEST_TEXTS.size, results.size)
        assertTrue("unexpected errors: ${results.flatMap { it.errors }}", results.all { it.errors.isEmpty() })
        assertTrue("all wavs should exist", results.all { File(it.wavPath).isFile && File(it.wavPath).length() > 44L })
    }

    private fun runWarmup(engine: TextToSpeechEngine) {
        val listener = AudioCaptureListener("warmup")
        engine.setListener(listener)
        engine.speak("这是 decoder 对比测试的预热句。", speakParams("warmup-$runId"))
        assertTrue("warmup synthesis timeout", listener.synthesisCompleteLatch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS))
        assertTrue("warmup errors: ${listener.errors}", listener.errors.isEmpty())
    }

    private fun runSpeak(engine: TextToSpeechEngine, index: Int, text: String): AudioDumpResult {
        val caseId = "case-%02d".format(index)
        val requestId = "$variant-$caseId-$runId"
        val listener = AudioCaptureListener(caseId)
        engine.setListener(listener)
        val submitAtMs = SystemClock.elapsedRealtime()
        engine.speak(text, speakParams(requestId))
        val completed = listener.synthesisCompleteLatch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS)
        val pcm = listener.audioBytes.toByteArray()
        val wavFile = File(outputDir, "$caseId-$variant.wav")
        wavFile.writeBytes(wavBytes(pcm, SAMPLE_RATE, CHANNELS, BITS_PER_SAMPLE))
        return AudioDumpResult(
            caseId = caseId,
            text = text,
            requestId = requestId,
            wavPath = wavFile.absolutePath,
            pcmBytes = pcm.size,
            firstPacketMs = listener.firstPacketMs,
            synthesisMs = listener.synthesisMs,
            audioDurationMs = listener.audioDurationMs,
            rtf = listener.rtf,
            chunkCount = listener.chunkCount,
            submitToCompleteMs = if (listener.synthesisCompleteAtMs >= 0L) listener.synthesisCompleteAtMs - submitAtMs else -1L,
            completed = completed,
            profilingInfo = listener.profilingInfo,
            errors = listener.errors.toList(),
        )
    }

    private fun speakParams(requestId: String): SpeakParams =
        SpeakParams(
            requestId = requestId,
            speed = 1.0f,
            playType = PlayType.SYNTHESIZE_ONLY,
            queueMode = QueueMode.PREEMPT,
            languageContext = LANGUAGE,
            streamingConfig = TtsStreamingConfig(
                chunkSize = CHUNK_SIZE,
                firstChunkSize = FIRST_CHUNK_SIZE,
                pcmQueueCapacity = PCM_QUEUE_CAPACITY,
            ),
        )

    private class AudioCaptureListener(private val caseId: String) : SpeakListener {
        val synthesisCompleteLatch = CountDownLatch(1)
        val audioBytes = ByteArrayOutputStream()
        val errors = mutableListOf<String>()
        @Volatile var synthesisCompleteAtMs: Long = -1L
        @Volatile var firstPacketMs: Long = -1L
        @Volatile var synthesisMs: Long = -1L
        @Volatile var audioDurationMs: Long = -1L
        @Volatile var rtf: Double = -1.0
        @Volatile var profilingInfo: String = ""
        @Volatile var chunkCount: Int = 0

        override fun onStart(requestId: String, response: StartResponse) = Unit

        override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) {
            audioBytes.write(audio)
            chunkCount += 1
        }

        override fun onComplete(requestId: String, response: CompleteResponse) {
            if (response.type == CompleteType.SYNTHESIS_COMPLETE) {
                firstPacketMs = response.firstPacketMs
                synthesisMs = response.synthesisMs
                audioDurationMs = response.audioDurationMs
                rtf = response.rtf
                profilingInfo = response.profilingInfo
                synthesisCompleteAtMs = SystemClock.elapsedRealtime()
                synthesisCompleteLatch.countDown()
            }
        }

        override fun onStop(requestId: String, response: StopResponse) = Unit

        override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
            errors += "$caseId:$requestId:$errorCode:$errorMessage"
            synthesisCompleteLatch.countDown()
        }
    }

    private data class AudioDumpResult(
        val caseId: String,
        val text: String,
        val requestId: String,
        val wavPath: String,
        val pcmBytes: Int,
        val firstPacketMs: Long,
        val synthesisMs: Long,
        val audioDurationMs: Long,
        val rtf: Double,
        val chunkCount: Int,
        val submitToCompleteMs: Long,
        val completed: Boolean,
        val profilingInfo: String,
        val errors: List<String>,
    ) {
        fun toJson(): JSONObject = JSONObject()
            .put("caseId", caseId)
            .put("text", text)
            .put("requestId", requestId)
            .put("wavPath", wavPath)
            .put("pcmBytes", pcmBytes)
            .put("firstPacketMs", firstPacketMs)
            .put("synthesisMs", synthesisMs)
            .put("audioDurationMs", audioDurationMs)
            .put("rtf", rtf)
            .put("chunkCount", chunkCount)
            .put("submitToCompleteMs", submitToCompleteMs)
            .put("completed", completed)
            .put("profilingInfo", profilingInfo)
            .put("errors", JSONArray(errors))
    }

    companion object {
        private const val TAG = "AarDecoderDump20"
        private const val LANGUAGE = "zh-en"
        private const val VOICE_ID = "lits-female-02"
        private const val TIMEOUT_MS = 90_000L
        private const val INTER_SPEAK_SLEEP_MS = 100L
        private const val CHUNK_SIZE = 50
        private const val FIRST_CHUNK_SIZE = 50
        private const val PCM_QUEUE_CAPACITY = 128
        private const val SAMPLE_RATE = 24_000
        private const val CHANNELS = 1
        private const val BITS_PER_SAMPLE = 16
        private val TEST_TEXTS = listOf(
            "今天天气不错，我们一起测试语音合成。",
            "请在下午三点半提醒我开会。",
            "当前温度是零下二十四点五度。",
            "二零二六年七月十四日，系统完成更新。",
            "A60B59 这个编号需要保持清晰。",
            "请播放第一首歌，然后把音量调低。",
            "订单金额是一千二百三十四点五六元。",
            "The quick brown fox jumps over the lazy dog.",
            "请确认 Wi-Fi、Bluetooth 和 GPS 都已经打开。",
            "区老师和曾老师今天都会参加评审。",
            "薄荷味的饮料放在左边第二排。",
            "这个功能用于比较 chunk decoder 和 final decoder。",
            "请把文件保存到 /sdcard/test/audio.wav。",
            "成功率从百分之二十提升到百分之八十。",
            "Hello，小爱同学，请打开客厅的灯。",
            "下一站是人民广场，请从右侧车门下车。",
            "请连续朗读这句话，观察句尾是否自然。",
            "我们先跑双 decoder，再跑单 decoder。",
            "今天的测试文本不需要太长。",
            "最后一条样例用于检查收尾音频。",
        )

        private fun wavBytes(pcm: ByteArray, sampleRate: Int, channels: Int, bitsPerSample: Int): ByteArray {
            val byteRate = sampleRate * channels * bitsPerSample / 8
            val blockAlign = channels * bitsPerSample / 8
            val dataSize = pcm.size
            val buffer = ByteBuffer.allocate(44 + dataSize).order(ByteOrder.LITTLE_ENDIAN)
            buffer.put("RIFF".toByteArray(Charsets.US_ASCII))
            buffer.putInt(36 + dataSize)
            buffer.put("WAVE".toByteArray(Charsets.US_ASCII))
            buffer.put("fmt ".toByteArray(Charsets.US_ASCII))
            buffer.putInt(16)
            buffer.putShort(1.toShort())
            buffer.putShort(channels.toShort())
            buffer.putInt(sampleRate)
            buffer.putInt(byteRate)
            buffer.putShort(blockAlign.toShort())
            buffer.putShort(bitsPerSample.toShort())
            buffer.put("data".toByteArray(Charsets.US_ASCII))
            buffer.putInt(dataSize)
            buffer.put(pcm)
            return buffer.array()
        }

        private fun instrumentationArg(name: String): String? =
            androidx.test.platform.app.InstrumentationRegistry.getArguments().getString(name)

        private fun JSONObject.toCompactString(): String = toString().replace('\n', ' ')
    }
}
