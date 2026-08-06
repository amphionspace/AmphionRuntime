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

class AarContextAudioComparisonDeviceTest {
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()
    private val outputDir = File(
        context.getExternalFilesDir(null) ?: context.filesDir,
        "aar-context-audio-comparison",
    ).apply { mkdirs() }
    private val runId = "context-audio-${System.currentTimeMillis()}"

    @Test
    fun synthesizeSameTextWithContextVariantsAndSaveWavs() {
        TextToSpeechSdk.setWorkPath(File(context.cacheDir, "aar-context-audio-work").apply {
            deleteRecursively()
            mkdirs()
        }.absolutePath)

        val engine = TextToSpeechSdk.createEngine(
            CreateEngineParams(
                language = LANGUAGE,
                mode = RunMode.OFFLINE,
                voiceId = VOICE_ID,
                engineName = runId,
            ),
        )
        val results = mutableListOf<ContextAudioResult>()
        try {
            runWarmup(engine)
            CONTEXT_VALUES.forEach { contextFrames ->
                val result = runSpeak(engine, contextFrames)
                results += result
                Log.i(TAG, "context=$contextFrames result=${result.toJson().toCompactString()}")
                Thread.sleep(INTER_SPEAK_SLEEP_MS)
            }
        } finally {
            runCatching { engine.shutdown() }
        }

        val summary = JSONObject()
            .put("runId", runId)
            .put("devicePackage", context.packageName)
            .put("integrationPath", "aarHost implementation(files(\"../sdk/build/outputs/aar/sdk-release.aar\"))")
            .put("text", TEST_TEXT)
            .put("textLength", TEST_TEXT.length)
            .put("language", LANGUAGE)
            .put("voiceId", VOICE_ID)
            .put("playType", PlayType.SYNTHESIZE_ONLY.name)
            .put("queueMode", QueueMode.PREEMPT.name)
            .put("flowStep", FLOW_STEP)
            .put("chunkSize", CHUNK_SIZE)
            .put("firstChunkSize", FIRST_CHUNK_SIZE)
            .put("pcmQueueCapacity", PCM_QUEUE_CAPACITY)
            .put("contexts", JSONArray(CONTEXT_VALUES))
            .put("results", JSONArray(results.map { it.toJson() }))
        val summaryFile = File(outputDir, "summary-$runId.json")
        summaryFile.writeText(summary.toString(2) + "\n", Charsets.UTF_8)

        assertEquals("context result count", CONTEXT_VALUES.size, results.size)
        assertTrue("unexpected errors: ${results.flatMap { it.errors }}", results.all { it.errors.isEmpty() })
        assertTrue("all wavs should exist", results.all { File(it.wavPath).isFile && File(it.wavPath).length() > 44L })
    }

    private fun runWarmup(engine: TextToSpeechEngine) {
        val listener = AudioCaptureListener("warmup")
        engine.setListener(listener)
        engine.speak(
            "这是 context 音频对比测试的预热句。",
            speakParams(requestId = "warmup-$runId", contextFrames = CONTEXT_VALUES.first()),
        )
        assertTrue("warmup synthesis timeout", listener.synthesisCompleteLatch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS))
        assertTrue("warmup errors: ${listener.errors}", listener.errors.isEmpty())
    }

    private fun runSpeak(engine: TextToSpeechEngine, contextFrames: Int): ContextAudioResult {
        val requestId = "context-$contextFrames-$runId"
        val listener = AudioCaptureListener("context-$contextFrames")
        engine.setListener(listener)
        val submitAtMs = SystemClock.elapsedRealtime()
        engine.speak(TEST_TEXT, speakParams(requestId, contextFrames))
        val completed = listener.synthesisCompleteLatch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS)
        val pcm = listener.audioBytes.toByteArray()
        val wavFile = File(outputDir, "context_${contextFrames}_$runId.wav")
        wavFile.writeBytes(wavBytes(pcm, SAMPLE_RATE, CHANNELS, BITS_PER_SAMPLE))
        return ContextAudioResult(
            contextFrames = contextFrames,
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

    private fun speakParams(requestId: String, contextFrames: Int): SpeakParams =
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
            extraParams = mapOf(
                "flowStep" to FLOW_STEP,
                "previousChunkContextFrames" to contextFrames,
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

    private data class ContextAudioResult(
        val contextFrames: Int,
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
            .put("contextFrames", contextFrames)
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
        private const val TAG = "AarContextAudio"
        private const val LANGUAGE = "zh-en"
        private const val VOICE_ID = "lits-female-02"
        private const val TIMEOUT_MS = 180_000L
        private const val INTER_SPEAK_SLEEP_MS = 200L
        private const val FLOW_STEP = 4
        private const val CHUNK_SIZE = 50
        private const val FIRST_CHUNK_SIZE = 25
        private const val PCM_QUEUE_CAPACITY = 128
        private const val SAMPLE_RATE = 24_000
        private const val CHANNELS = 1
        private const val BITS_PER_SAMPLE = 16
        private val CONTEXT_VALUES = listOf(0, 8, 16, 24, 50)
        private const val TEST_TEXT =
            "今天我们用同一段较长文本，对比不同 decoder context 帧数对语音连续性和边界听感的影响。" +
                "这段话会故意包含多个逗号、停顿和连续短句，方便观察每个 chunk 之间是否出现断裂、重复、吞字或者音色变化。" +
                "如果 context 太短，理论上边界处可能更容易听到不自然；如果 context 太长，计算量会增加但可能更稳。" +
                "请重点听每一句衔接处、标点停顿处，以及长句后半段的稳定性。"

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

        private fun JSONObject.toCompactString(): String = toString().replace('\n', ' ')
    }
}
