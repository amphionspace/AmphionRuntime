package com.amphion.dingqiao.demo

import android.content.Context
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
 * Regression coverage for fast file-style feeding followed by finish().
 *
 * Before the fix, a fast feed could enqueue several endpoint finals into the async post-processor;
 * the first final after finish() was treated as the last one, closing the session and dropping
 * later queued finals. Files 04/06/11 then returned empty results with a short pre-finish settle.
 */
@RunWith(AndroidJUnit4::class)
class DingqiaoFinishFlushRegressionTest {

    private val targetContext: Context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val testContext: Context get() = InstrumentationRegistry.getInstrumentation().context

    @Test
    fun fastFeedFinishDoesNotDropQueuedFinals() {
        val wavs = mainWavs()
        val selected = selectedRegressionWavs(wavs)
        val report = File(targetContext.filesDir, "eval_reports/finish_flush_regression.tsv").apply {
            parentFile?.mkdirs()
            writeText("file\trealtime\tfast_short_settle\tfast_long_settle\n", Charsets.UTF_8)
        }

        val engine = createEngine()
        try {
            for (wav in selected) {
                val pcm = readMonoPcm16As16k(wav, testContext.assets.open(wav).use { it.readBytes() })
                val realtime = decode(engine, "rt-${wav.sessionTag()}", pcm, frameSleepMs = 20, drainMs = 300)
                val fastShortSettle = decode(engine, "fs-${wav.sessionTag()}", pcm, frameSleepMs = 0, drainMs = 300)
                val fastLongSettle = decode(engine, "fl-${wav.sessionTag()}", pcm, frameSleepMs = 0, drainMs = 3_000)
                report.appendText(
                    listOf(wav, realtime, fastShortSettle, fastLongSettle)
                        .joinToString("\t") { it.replace('\t', ' ') } + "\n",
                    Charsets.UTF_8,
                )

                assertTrue("$wav realtime should produce text", realtime.isNotBlank())
                assertTrue("$wav fast short-settle should not drop all finals", fastShortSettle.isNotBlank())
                assertTrue("$wav fast long-settle should produce text", fastLongSettle.isNotBlank())
                assertTrue(
                    "$wav fast short-settle too short: rt=${realtime.length} fast=${fastShortSettle.length}",
                    fastShortSettle.length >= (realtime.length * 0.8).toInt(),
                )
            }
        } finally {
            engine.shutdown()
        }
    }

    @Test
    fun assetLicenseInfoReflectsRuntimeLicense() {
        prepareSdkRuntime(
            testContext,
            targetContext,
            File(targetContext.getExternalFilesDir(null), "dingqiao_work_license"),
        )
        val engine = SpeechRecognizeSdk.createEngine(
            CreateEngineParams(
                language = "zh-CN",
                online = DingqiaoOnlineMode.OFFLINE,
            ),
        )
        try {
            val info = SpeechRecognizeSdk.getLicenseInfo()
            assertTrue("asset license should be active", info.status == 0)
            assertTrue("asset license should include ASR", info.authorizedFeatures.contains("ASR"))
        } finally {
            engine.shutdown()
        }
    }

    @Test
    fun generatedSessionTagIsValidForUnicodeAssetName() {
        val tag = "你可真会挑时候啊.wav".sessionTag()

        assertTrue("session tag must satisfy the public SDK contract: $tag",
            tag.matches(Regex("^[A-Za-z0-9_-]+$")))
    }

    private fun createEngine(): SpeechRecognitionEngine {
        prepareSdkRuntime(
            testContext,
            targetContext,
            File(targetContext.getExternalFilesDir(null), "dingqiao_work_finish_flush"),
        )
        return SpeechRecognizeSdk.createEngine(
            CreateEngineParams(
                language = "zh-CN",
                online = DingqiaoOnlineMode.OFFLINE,
                extraParams = mapOf("vadEnd" to 800),
            ),
        )
    }

    private fun decode(
        engine: SpeechRecognitionEngine,
        sessionId: String,
        pcm: ByteArray,
        frameSleepMs: Long,
        drainMs: Long,
    ): String {
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
        assertTrue("$sessionId start timeout/errors=$errors", started.await(15, TimeUnit.SECONDS))
        feedFrames(engine, sessionId, pcm, frameSleepMs)
        feedFrames(engine, sessionId, ByteArray(SAMPLE_RATE * 2), frameSleepMs = 0)
        Thread.sleep(drainMs)
        engine.finish(sessionId)
        assertTrue("$sessionId complete timeout/errors=$errors", completed.await(30, TimeUnit.SECONDS))
        assertTrue("$sessionId errors=$errors", errors.isEmpty())
        Thread.sleep(300)
        return finals.joinToString("")
    }

    private fun feedFrames(engine: SpeechRecognitionEngine, sessionId: String, pcmBytes: ByteArray, frameSleepMs: Long) {
        var offset = 0
        while (offset < pcmBytes.size) {
            val n = minOf(FRAME_BYTES, pcmBytes.size - offset)
            val frame = ByteArray(FRAME_BYTES)
            System.arraycopy(pcmBytes, offset, frame, 0, n)
            engine.writeAudio(sessionId, frame)
            offset += n
            if (frameSleepMs > 0) Thread.sleep(frameSleepMs)
        }
    }

    private fun mainWavs(): List<String> =
        wavAssets("")
            .filter {
                it.endsWith(".wav", ignoreCase = true) &&
                    !it.substringAfterLast('/').startsWith("._") &&
                    !it.contains("声纹")
            }
            .sorted()

    private fun selectedRegressionWavs(wavs: List<String>): List<String> {
        val supported = wavs.filter { isSupportedMonoPcm16Wav(it) }
        require(supported.size >= 4) {
            "need at least 4 mono PCM16 wav assets; found ${wavs.size} wav assets " +
                "but only ${supported.size} supported. Run with -PdingqiaoEvalAudioDir=/path/to/audio"
        }
        val preferred = listOf("04", "06", "11", "01").mapNotNull { prefix ->
            supported.firstOrNull { it.substringAfterLast('/').startsWith(prefix) }
        }
        return if (preferred.size == 4) preferred else supported.take(4)
    }

    private fun wavAssets(path: String): List<String> {
        val children = testContext.assets.list(path).orEmpty()
        if (children.isEmpty()) return if (path.endsWith(".wav", ignoreCase = true)) listOf(path) else emptyList()
        return children.flatMap { child ->
            wavAssets(if (path.isBlank()) child else "$path/$child")
        }
    }

    private fun isSupportedMonoPcm16Wav(assetName: String): Boolean =
        runCatching {
            val header = testContext.assets.open(assetName).use { input ->
                ByteArray(4096).let { buffer ->
                    val count = input.read(buffer)
                    if (count <= 0) ByteArray(0) else buffer.copyOf(count)
                }
            }
            val spec = readWavFormat(assetName, header)
            spec.sampleRate > 0 && spec.channels == 1 && spec.bits == 16
        }.getOrDefault(false)

    private fun String.sessionTag(): String =
        "${hashCode().toUInt().toString(16)}-${System.nanoTime().toULong().toString(16)}"

    private fun readMonoPcm16As16k(name: String, bytes: ByteArray): ByteArray {
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
        require(sampleRate > 0 && channels == 1 && bits == 16) {
            "expected mono PCM16, got sr=$sampleRate ch=$channels bits=$bits file=$name"
        }
        require(dataOffset >= 0 && dataBytes > 0) { "missing data chunk: $name" }
        val pcm = bytes.copyOfRange(dataOffset, dataOffset + dataBytes)
        return if (sampleRate == SAMPLE_RATE) pcm else resamplePcm16Mono(pcm, sampleRate, SAMPLE_RATE)
    }

    private fun resamplePcm16Mono(pcm: ByteArray, sourceRate: Int, targetRate: Int): ByteArray {
        require(sourceRate > 0 && targetRate > 0) { "bad sample rate: source=$sourceRate target=$targetRate" }
        val sourceSamples = pcm.size / 2
        if (sourceSamples == 0) return ByteArray(0)

        val targetSamples = ((sourceSamples.toLong() * targetRate) / sourceRate).toInt().coerceAtLeast(1)
        val out = ByteBuffer.allocate(targetSamples * 2).order(ByteOrder.LITTLE_ENDIAN)
        for (i in 0 until targetSamples) {
            val sourcePos = i.toDouble() * sourceRate / targetRate
            val index = sourcePos.toInt().coerceIn(0, sourceSamples - 1)
            val nextIndex = (index + 1).coerceAtMost(sourceSamples - 1)
            val fraction = sourcePos - index
            val sample = sampleAt(pcm, index) + (sampleAt(pcm, nextIndex) - sampleAt(pcm, index)) * fraction
            out.putShort(Math.round(sample).toInt().coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt()).toShort())
        }
        return out.array()
    }

    private fun sampleAt(pcm: ByteArray, sampleIndex: Int): Int {
        val offset = sampleIndex * 2
        return (pcm[offset].toInt() and 0xff) or (pcm[offset + 1].toInt() shl 8)
    }

    private fun readWavFormat(name: String, bytes: ByteArray): WavSpec {
        require(bytes.size >= 44) { "wav header too small: $name" }
        val buf = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        require(buf.int == fourCc("RIFF")) { "missing RIFF: $name" }
        buf.int
        require(buf.int == fourCc("WAVE")) { "missing WAVE: $name" }

        while (buf.remaining() >= 8) {
            val id = buf.int
            val size = buf.int
            require(size >= 0) { "bad chunk size: $name" }
            if (id == fourCc("fmt ")) {
                val format = buf.short.toInt() and 0xffff
                val channels = buf.short.toInt() and 0xffff
                val sampleRate = buf.int
                buf.int
                buf.short
                val bits = buf.short.toInt() and 0xffff
                require(format == 1) { "only PCM wav supported: $name" }
                return WavSpec(sampleRate, channels, bits)
            }
            if (size > buf.remaining()) break
            buf.position(buf.position() + size)
        }
        error("missing fmt chunk: $name")
    }

    private fun fourCc(s: String): Int {
        val b = s.toByteArray(Charsets.US_ASCII)
        return (b[0].toInt() and 0xff) or
            ((b[1].toInt() and 0xff) shl 8) or
            ((b[2].toInt() and 0xff) shl 16) or
            ((b[3].toInt() and 0xff) shl 24)
    }

    private data class WavSpec(val sampleRate: Int, val channels: Int, val bits: Int)

    private companion object {
        private const val SAMPLE_RATE = 16_000
        private const val FRAME_BYTES = 640
    }
}
