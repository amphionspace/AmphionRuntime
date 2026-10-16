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
import com.amphion.police.PoliceEnhancePipeline
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
 *   -PdingqiaoEvalAudioDir=/path/to/audio \
 *   -Pandroid.testInstrumentationRunnerArguments.class=com.amphion.dingqiao.demo.DingqiaoAudioCorpusInstrumentedTest
 */
@RunWith(AndroidJUnit4::class)
class DingqiaoAudioCorpusInstrumentedTest {

    @Test
    fun policeFeedbackCorrectionsPreserveValidText() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val cases = listOf(
            "玉露是否开启？" to "预录是否开启？",
            "沿路是否开启？" to "延录是否开启？",
            "视频增速支持哪些？" to "视频帧率支持哪些？",
            "视频证率支持哪些？" to "视频帧率支持哪些？",
            "记录仪沿路时长是多少？" to "记录仪延录时长是多少？",
            "关闭沿路。" to "关闭延录。",
            "打开沿路并设置为60秒。" to "打开延录并设置为60秒。",
            "打开沿路。" to "打开延录。",
            "打开记录仪WANG。" to "打开记录仪WLAN。",
            "打开记录仪PLAN。" to "打开记录仪WLAN。",
            "把镜头切换到超常待机模式。" to "把镜头切换到超长待机模式。",
            "查询沿路时长。" to "查询延录时长。",
            "布证。" to "补证。",
            "沿路风景很好。" to "沿路风景很好。",
            "请复述打开沿路这个错误。" to "请复述打开沿路这个错误。",
            "补正。" to "补正。",
            "把记录仪音量调到最大。" to "把记录仪音量调到最大。",
            "请您拨打855 4767电话。" to "请您拨打855 4767电话。",
            "讯问。" to "讯问。",
            "把录像分辨率设置为第一。" to "把录像分辨率设置为D1。",
            "E。警保。" to "e警保。",
        )
        PoliceEnhancePipeline.create(context).use { pipeline ->
            val failures = cases.mapNotNull { (input, expected) ->
                val actual = pipeline.enhance(input).text
                DqReport.append(context, mapOf(
                    "case" to "police_feedback", "input" to input,
                    "expected" to expected, "actual" to actual, "pass" to (actual == expected),
                ))
                if (actual == expected) null else "$input -> $actual (expected $expected)"
            }
            assertTrue(failures.joinToString("\n"), failures.isEmpty())
        }
    }

    @Test
    fun decodeEvalAudioCorpus() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val testContext = instrumentation.context
        val arguments = InstrumentationRegistry.getArguments()
        val audioPrefix = arguments.getString("audioPrefix").orEmpty()
        val policeEnhancementArg = arguments.getString("enablePoliceEnhancement")
        val policeEnhancement = policeEnhancementArg
            ?.toBooleanStrictOrNull()
            ?: run {
                require(policeEnhancementArg == null) {
                    "enablePoliceEnhancement must be true or false: $policeEnhancementArg"
                }
                true
            }
        val reportDir = File(context.filesDir, "eval_reports").apply { mkdirs() }
        val report = File(reportDir, "dingqiao_audio_eval.tsv")

        val wavFiles = testContext.assets.list("")
            .orEmpty()
            .filter { it.endsWith(".wav", ignoreCase = true) }
            .filter { audioPrefix.isEmpty() || it.startsWith(audioPrefix) }
            .sorted()
        assertTrue(
            "No wav assets found. Run with -PdingqiaoEvalAudioDir=/path/to/audio",
            wavFiles.isNotEmpty(),
        )

        prepareSdkRuntime(
            context,
            File(context.getExternalFilesDir(null), "dingqiao_work_eval"),
        )
        val engine = SpeechRecognizeSdk.createEngine(
            CreateEngineParams(
                language = "zh-CN",
                online = DingqiaoOnlineMode.OFFLINE,
                extraParams = mapOf("vadEnd" to 800),
            ),
        )

        report.writeText("file\tduration_s\tstatus\tfinal_count\ttext\terrors\n", Charsets.UTF_8)
        val cases = wavFiles.map { wavAssetName ->
            val result = decodeOne(engine, testContext, wavAssetName, policeEnhancement)
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
        policeEnhancement: Boolean,
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
                    "enablePoliceEnhancement" to policeEnhancement,
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
