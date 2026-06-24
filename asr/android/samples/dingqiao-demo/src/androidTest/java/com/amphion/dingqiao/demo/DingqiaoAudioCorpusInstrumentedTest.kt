package com.amphion.dingqiao.demo

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.AudioInfo
import com.amphion.dingqiao.CreateEngineParams
import com.amphion.dingqiao.DingqiaoOnlineMode
import com.amphion.dingqiao.RecognitionListener
import com.amphion.dingqiao.SpeechRecognitionEngine
import com.amphion.dingqiao.SpeechRecognitionResult
import com.amphion.dingqiao.SpeechRecognizeSdk
import com.amphion.dingqiao.StartParams
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Device-side corpus smoke test for Dingqiao delivery sample.
 *
 * Run with:
 * ./gradlew :samples:dingqiao-demo:connectedDebugAndroidTest \
 *   -PdingqiaoEvalAudioDir=/Users/boxp/Downloads/audio \
 *   -Pandroid.testInstrumentationRunnerArguments.class=com.amphion.dingqiao.demo.DingqiaoAudioCorpusInstrumentedTest
 */
@RunWith(AndroidJUnit4::class)
class DingqiaoAudioCorpusInstrumentedTest {

    @Test
    fun decodeEvalAudioCorpus() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val testContext = instrumentation.context
        val reportDir = File(context.filesDir, "eval_reports").apply { mkdirs() }
        val report = File(reportDir, "dingqiao_audio_eval.tsv")

        val wavFiles = testContext.assets.list("")
            .orEmpty()
            .filter { it.endsWith(".wav", ignoreCase = true) }
            .sorted()
        assertTrue(
            "No wav assets found. Run with -PdingqiaoEvalAudioDir=/Users/boxp/Downloads/audio",
            wavFiles.isNotEmpty(),
        )

        SpeechRecognizeSdk.init(context)
        SpeechRecognizeSdk.setWorkPath(File(context.getExternalFilesDir(null), "dingqiao_work_eval").absolutePath)
        val engine = SpeechRecognizeSdk.createEngine(
            CreateEngineParams(
                language = "zh-CN",
                online = DingqiaoOnlineMode.OFFLINE,
                extraParams = mapOf("vadEnd" to 800),
            ),
        )

        report.writeText("file\tduration_s\tstatus\tfinal_count\ttext\terrors\n", Charsets.UTF_8)
        val cases = wavFiles.map { wavAssetName ->
            val result = decodeOne(engine, testContext, wavAssetName)
            report.appendText(result.toTsvRow() + "\n", Charsets.UTF_8)
            result
        }
        engine.shutdown()

        val hardFailures = cases.filter { it.status == "ERROR" || it.status == "TIMEOUT" }
        assertTrue(
            "Hard failures=${hardFailures.size}; report=${report.absolutePath}; " +
                hardFailures.joinToString { it.assetName + ":" + it.errors.joinToString("|") },
            hardFailures.isEmpty(),
        )
    }

    private fun decodeOne(
        engine: SpeechRecognitionEngine,
        testContext: android.content.Context,
        wavAssetName: String,
    ): DecodeResult {
        val pcm = readWav16kMonoPcm(wavAssetName, testContext.assets.open(wavAssetName).use { it.readBytes() })
        val durationMs = pcm.size / 2L * 1000L / SAMPLE_RATE
        val sessionId = "eval-${Integer.toHexString(wavAssetName.hashCode())}-${System.currentTimeMillis()}"
        val started = CountDownLatch(1)
        val completed = CountDownLatch(1)
        val finals = Collections.synchronizedList(mutableListOf<String>())
        val errors = Collections.synchronizedList(mutableListOf<String>())

        engine.setListener(object : RecognitionListener {
            override fun onStart(sessionId: String, eventMessage: String) {
                started.countDown()
            }

            override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) = Unit

            override fun onResult(sessionId: String, result: SpeechRecognitionResult) {
                if (result.isFinal && result.result.isNotBlank()) finals.add(result.result)
            }

            override fun onComplete(sessionId: String, eventMessage: String) {
                completed.countDown()
            }

            override fun onError(sessionId: String, errorCode: Int, errorMessage: String) {
                errors.add("$errorCode:$errorMessage")
                completed.countDown()
            }
        })

        engine.startListening(
            StartParams(
                sessionId = sessionId,
                audioInfo = AudioInfo(),
                extraParams = mapOf(
                    "enablePartialResult" to true,
                    "maxAudioDuration" to 60_000,
                    "vadEnd" to 800,
                ),
            ),
        )
        val startStatus = waitForStartOrError(started, errors)
        if (startStatus != StartStatus.STARTED) {
            val startErrors = errors.toList().takeIf { it.isNotEmpty() } ?: listOf("start timeout")
            return DecodeResult(wavAssetName, durationMs, startStatus.name, finals.toList(), startErrors)
        }

        feedPcmRealtime(engine, sessionId, pcm)
        feedPcmRealtime(engine, sessionId, ByteArray(TAIL_SILENCE_BYTES))
        Thread.sleep(DRAIN_BUFFER_MS)
        engine.finish(sessionId)

        val done = completed.await(COMPLETE_TIMEOUT_SEC, TimeUnit.SECONDS)
        Thread.sleep(FINAL_COLLECT_MS)
        val status = when {
            !done -> "TIMEOUT"
            errors.isNotEmpty() -> "ERROR"
            finals.isEmpty() -> "EMPTY"
            else -> "OK"
        }
        return DecodeResult(wavAssetName, durationMs, status, finals.toList(), errors.toList())
    }

    private fun waitForStartOrError(
        started: CountDownLatch,
        errors: MutableList<String>,
    ): StartStatus {
        val deadline = System.currentTimeMillis() + TimeUnit.SECONDS.toMillis(START_TIMEOUT_SEC)
        while (System.currentTimeMillis() < deadline) {
            if (started.count == 0L) return StartStatus.STARTED
            if (errors.isNotEmpty()) return StartStatus.ERROR
            Thread.sleep(20)
        }
        return StartStatus.TIMEOUT
    }

    private fun feedPcmRealtime(engine: SpeechRecognitionEngine, sessionId: String, pcmBytes: ByteArray) {
        var offset = 0
        while (offset < pcmBytes.size) {
            val n = minOf(FRAME_BYTES, pcmBytes.size - offset)
            val frame = ByteArray(FRAME_BYTES)
            System.arraycopy(pcmBytes, offset, frame, 0, n)
            engine.writeAudio(sessionId, frame)
            offset += n
            Thread.sleep(FRAME_DURATION_MS)
        }
    }

    private fun readWav16kMonoPcm(name: String, bytes: ByteArray): ByteArray {
        require(bytes.size >= 44) { "wav too small: $name" }
        val buf = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        require(buf.int == fourCc("RIFF")) { "missing RIFF: $name" }
        buf.int
        require(buf.int == fourCc("WAVE")) { "missing WAVE: $name" }

        var sampleRate = 0
        var channels = 0
        var bits = 0
        var dataOffset = -1
        var dataBytes = 0
        while (buf.remaining() >= 8) {
            val id = buf.int
            val size = buf.int
            require(size >= 0 && buf.remaining() >= size) { "bad chunk size: $name" }
            when (id) {
                fourCc("fmt ") -> {
                    val start = buf.position()
                    val format = buf.short.toInt() and 0xffff
                    channels = buf.short.toInt() and 0xffff
                    sampleRate = buf.int
                    buf.int
                    buf.short
                    bits = buf.short.toInt() and 0xffff
                    require(format == 1) { "only PCM wav supported: $name" }
                    buf.position(start + size)
                }
                fourCc("data") -> {
                    dataOffset = buf.position()
                    dataBytes = size
                    buf.position(dataOffset + size)
                }
                else -> buf.position(buf.position() + size)
            }
        }
        require(sampleRate == SAMPLE_RATE && channels == 1 && bits == 16) {
            "expected 16k mono PCM16, got sr=$sampleRate ch=$channels bits=$bits file=$name"
        }
        require(dataOffset >= 0 && dataBytes > 0) { "missing data chunk: $name" }
        return bytes.copyOfRange(dataOffset, dataOffset + dataBytes)
    }

    private fun fourCc(s: String): Int {
        val b = s.toByteArray(Charsets.US_ASCII)
        return (b[0].toInt() and 0xff) or
            ((b[1].toInt() and 0xff) shl 8) or
            ((b[2].toInt() and 0xff) shl 16) or
            ((b[3].toInt() and 0xff) shl 24)
    }

    private data class DecodeResult(
        val assetName: String,
        val durationMs: Long,
        val status: String,
        val finals: List<String>,
        val errors: List<String>,
    ) {
        fun toTsvRow(): String =
            listOf(
                assetName,
                "%.3f".format(durationMs / 1000.0),
                status,
                finals.size.toString(),
                finals.joinToString(" ").replace('\t', ' '),
                errors.joinToString(" | ").replace('\t', ' '),
            ).joinToString("\t")
    }

    private enum class StartStatus { STARTED, ERROR, TIMEOUT }

    private companion object {
        private const val SAMPLE_RATE = 16_000
        private const val FRAME_BYTES = 640
        private const val FRAME_DURATION_MS = 20L
        private const val TAIL_SILENCE_BYTES = SAMPLE_RATE * 2
        private const val START_TIMEOUT_SEC = 10L
        private const val COMPLETE_TIMEOUT_SEC = 20L
        private const val DRAIN_BUFFER_MS = 1_200L
        private const val FINAL_COLLECT_MS = 600L
    }
}
