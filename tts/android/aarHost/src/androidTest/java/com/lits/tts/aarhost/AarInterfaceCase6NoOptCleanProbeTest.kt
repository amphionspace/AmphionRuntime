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
import com.lits.tts.sdk.TextToSpeechSdk
import com.lits.tts.sdk.TtsStreamingConfig
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Test

class AarInterfaceCase6NoOptCleanProbeTest {
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()
    private val outputDir = File(
        context.getExternalFilesDir(null) ?: context.filesDir,
        "aar-case6-noopt-clean-probe",
    ).apply { mkdirs() }
    private val runId = "dingqiao-case6-noopt-clean-${System.currentTimeMillis()}"

    @Test
    fun probeCase6NoOptClean() {
        TextToSpeechSdk.setWorkPath(File(context.cacheDir, "dingqiao-case6-noopt-clean-work").apply {
            deleteRecursively()
            mkdirs()
        }.absolutePath)

        val createEngineStartMs = SystemClock.elapsedRealtime()
        val engine = TextToSpeechSdk.createEngine(
            CreateEngineParams(
                language = LANGUAGE,
                mode = RunMode.OFFLINE,
                voiceId = VOICE_ID,
                engineName = runId,
                modelLoadOnCreate = true,
            ),
        )
        val createEngineMs = SystemClock.elapsedRealtime() - createEngineStartMs

        val listener = ProbeListener()
        engine.setListener(listener)
        try {
            val submitAtMs = SystemClock.elapsedRealtime()
            engine.speak(TEST_TEXT, speakParams("case6-$runId"))
            val completed = listener.synthesisCompleteLatch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS)
            val result = JSONObject()
                .put("runId", runId)
                .put("integrationPath", "aarHost implementation(files(\"../sdk/build/outputs/aar/sdk-release.aar\"))")
                .put("devicePackage", context.packageName)
                .put("hostApkSha256", sha256(File(context.applicationInfo.sourceDir)))
                .put("aarSha256", AAR_SHA256)
                .put("manifestStreamDecoderTimesteps", MANIFEST_STREAM_DECODER_TIMESTEPS)
                .put("ortBytecodeOptimization", ORT_BYTECODE_OPTIMIZATION)
                .put("ortBytecodeSessionLoadIntraOpThreads", ORT_BYTECODE_SESSION_LOAD_INTRA_OP_THREADS)
                .put("ortSourceOptimization", "NO_OPT")
                .put("ortSourceSessionLoadIntraOpThreads", 1)
                .put("language", LANGUAGE)
                .put("voiceId", VOICE_ID)
                .put("text", TEST_TEXT)
                .put("textLength", TEST_TEXT.length)
                .put("speed", SPEED.toDouble())
                .put("pitch", PITCH.toDouble())
                .put("volume", VOLUME.toDouble())
                .put("playType", PlayType.SYNTHESIZE_ONLY.name)
                .put("queueMode", QueueMode.PREEMPT.name)
                .put("chunkSize", CHUNK_SIZE)
                .put("firstChunkSize", CHUNK_SIZE)
                .put("pcmQueueCapacity", PCM_QUEUE_CAPACITY)
                .put("createEngineMs", createEngineMs)
                .put("submitToStartMs", listener.startAtMs - submitAtMs)
                .put("submitToSynthesisCompleteMs", listener.synthesisCompleteAtMs - submitAtMs)
                .put("firstPacketMs", listener.firstPacketMs)
                .put("synthesisMs", listener.synthesisMs)
                .put("audioDurationMs", listener.audioDurationMs)
                .put("rtf", listener.rtf)
                .put("profilingInfo", listener.profilingInfo)
                .put("loadProfileInfo", listener.loadProfileInfo)
                .put("effectiveStreamingChunkSize", listener.effectiveStreamingChunkSize)
                .put("effectivePcmQueueCapacity", listener.effectivePcmQueueCapacity)
                .put("completed", completed)
                .put("errors", JSONArray(listener.errors))

            File(outputDir, "result.json").writeText(result.toString(2) + "\n", Charsets.UTF_8)
            Log.i(TAG, "result=$result outputDir=${outputDir.absolutePath}")

            assertTrue("synthesis timeout", completed)
            assertTrue("unexpected errors: ${listener.errors}", listener.errors.isEmpty())
            assertTrue("missing rtf", listener.rtf >= 0.0)
        } finally {
            runCatching { engine.shutdown() }
        }
    }

    private fun speakParams(requestId: String): SpeakParams =
        SpeakParams(
            requestId = requestId,
            speed = SPEED,
            volume = VOLUME,
            pitch = PITCH,
            playType = PlayType.SYNTHESIZE_ONLY,
            queueMode = QueueMode.PREEMPT,
            languageContext = LANGUAGE,
            streamingConfig = TtsStreamingConfig(
                chunkSize = CHUNK_SIZE,
                firstChunkSize = CHUNK_SIZE,
                pcmQueueCapacity = PCM_QUEUE_CAPACITY,
            ),
        )

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val read = input.read(buffer)
                if (read <= 0) break
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private class ProbeListener : SpeakListener {
        val synthesisCompleteLatch = CountDownLatch(1)
        val errors = mutableListOf<String>()
        @Volatile var startAtMs: Long = -1L
        @Volatile var synthesisCompleteAtMs: Long = -1L
        @Volatile var firstPacketMs: Long = -1L
        @Volatile var synthesisMs: Long = -1L
        @Volatile var audioDurationMs: Long = -1L
        @Volatile var rtf: Double = -1.0
        @Volatile var profilingInfo: String = ""
        @Volatile var loadProfileInfo: String = ""
        @Volatile var effectiveStreamingChunkSize: Int = -1
        @Volatile var effectivePcmQueueCapacity: Int = -1

        override fun onStart(requestId: String, response: StartResponse) {
            startAtMs = SystemClock.elapsedRealtime()
            loadProfileInfo = response.loadProfileInfo
            effectiveStreamingChunkSize = response.streamingChunkSize
            effectivePcmQueueCapacity = response.pcmQueueCapacity
        }

        override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) = Unit

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
            errors += "$requestId:$errorCode:$errorMessage"
            synthesisCompleteLatch.countDown()
        }
    }

    companion object {
        private const val TAG = "DingqiaoCase6NoOpt"
        private const val LANGUAGE = "zh-en"
        private const val VOICE_ID = "lits-female-02"
        private const val TEST_TEXT = "SDK 冒烟稳定性样例 7。Mixed stability payload with Androi。"
        private const val SPEED = 0.75f
        private const val PITCH = 0.8f
        private const val VOLUME = 0.8f
        private const val CHUNK_SIZE = 32
        private const val PCM_QUEUE_CAPACITY = 8
        private const val TIMEOUT_MS = 180_000L
        private const val AAR_SHA256 = "dd3846a377ff89a3081387322fbb7751855f78f1339efe11aea38f4c06d38368"
        private const val MANIFEST_STREAM_DECODER_TIMESTEPS = 10
        private const val ORT_BYTECODE_OPTIMIZATION = "NO_OPT"
        private const val ORT_BYTECODE_SESSION_LOAD_INTRA_OP_THREADS = 1
    }
}
