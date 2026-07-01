package com.amphion.dingqiao.demo

import android.content.Context
import com.amphion.dingqiao.RecognitionListener
import com.amphion.dingqiao.SpeechRecognitionEngine
import com.amphion.dingqiao.SpeechRecognitionResult
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONObject

/**
 * 鼎桥 SDK corner-case 测试共享支撑：WAV 解析、PCM 帧喂入、回调采集、JSONL 报告。
 *
 * 设计取向：测试既要断言关键不变量，也要把可观测行为落进报告文件，便于人工复核 corner case。
 */
const val DQ_SR = 16_000
const val DQ_FRAME = 640
const val DQ_FRAME_MS = 20L

/** 线程安全采集所有回调，供断言与报告使用。 */
class CapturingListener : RecognitionListener {
    val partials: MutableList<String> = Collections.synchronizedList(mutableListOf())
    val finals: MutableList<SpeechRecognitionResult> = Collections.synchronizedList(mutableListOf())
    val events: MutableList<Pair<Int, String>> = Collections.synchronizedList(mutableListOf())
    val errors: MutableList<Pair<Int, String>> = Collections.synchronizedList(mutableListOf())
    val completes: MutableList<String> = Collections.synchronizedList(mutableListOf())

    @Volatile var started = CountDownLatch(1)
    @Volatile var complete = CountDownLatch(1)
    @Volatile var firstError = CountDownLatch(1)

    override fun onStart(sessionId: String, eventMessage: String) {
        started.countDown()
    }

    override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) {
        events.add(eventCode to eventMessage)
    }

    override fun onResult(sessionId: String, result: SpeechRecognitionResult) {
        if (result.isFinal) finals.add(result) else partials.add(result.result)
    }

    override fun onComplete(sessionId: String, eventMessage: String) {
        completes.add(eventMessage)
        complete.countDown()
    }

    override fun onError(sessionId: String, errorCode: Int, errorMessage: String) {
        errors.add(errorCode to errorMessage)
        firstError.countDown()
        complete.countDown()
    }

    fun finalText(): String = finals.filter { it.result.isNotBlank() }.joinToString("") { it.result }
    fun lastFinal(): SpeechRecognitionResult? = finals.lastOrNull()
    fun awaitStarted(ms: Long): Boolean = started.await(ms, TimeUnit.MILLISECONDS)
    fun awaitComplete(ms: Long): Boolean = complete.await(ms, TimeUnit.MILLISECONDS)
    fun awaitError(ms: Long): Boolean = firstError.await(ms, TimeUnit.MILLISECONDS)
    fun errorCodes(): List<Int> = errors.map { it.first }
}

/** 把任意长度 PCM 切成 640 字节帧喂入；最后不足一帧的补零（交付接口要求定长帧）。 */
fun feedFrames(engine: SpeechRecognitionEngine, sessionId: String, pcm: ByteArray, frameSleepMs: Long) {
    var offset = 0
    while (offset < pcm.size) {
        val n = minOf(DQ_FRAME, pcm.size - offset)
        val frame = ByteArray(DQ_FRAME)
        System.arraycopy(pcm, offset, frame, 0, n)
        engine.writeAudio(sessionId, frame)
        offset += n
        if (frameSleepMs > 0) Thread.sleep(frameSleepMs)
    }
}

/** 追加一段静音帧（ms）。 */
fun feedSilence(engine: SpeechRecognitionEngine, sessionId: String, ms: Int) {
    if (ms <= 0) return
    val bytes = ByteArray(DQ_SR * 2 * ms / 1000)
    feedFrames(engine, sessionId, bytes, 0)
}

/** 阻塞直到引擎空闲或超时。cancel() 后同步置空闲；finish() 后在回调线程异步置空闲。 */
fun awaitIdle(engine: SpeechRecognitionEngine, timeoutMs: Long = 8_000) {
    val deadline = System.currentTimeMillis() + timeoutMs
    while (engine.isBusy() && System.currentTimeMillis() < deadline) Thread.sleep(20)
}

object DqWav {
    fun read16kMonoPcm(name: String, bytes: ByteArray): ByteArray {
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
                    buf.short
                    channels = buf.short.toInt() and 0xffff
                    sampleRate = buf.int
                    buf.int
                    buf.short
                    bits = buf.short.toInt() and 0xffff
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
        require(sampleRate == DQ_SR && channels == 1 && bits == 16) {
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
}

/** 读取 androidTest 资产里的 wav 为 16k mono PCM。 */
fun readAssetPcm(testContext: Context, assetName: String): ByteArray =
    DqWav.read16kMonoPcm(assetName, testContext.assets.open(assetName).use { it.readBytes() })

/** 把 androidTest 资产文件落到 targetContext.filesDir，返回绝对路径（用于 registerVoiceprint / setLicense）。 */
fun stageAsset(testContext: Context, targetContext: Context, assetName: String, outName: String): String {
    val out = File(targetContext.filesDir, outName)
    out.parentFile?.mkdirs()
    testContext.assets.open(assetName).use { input -> out.outputStream().use { input.copyTo(it) } }
    return out.absolutePath
}

/** 追加一行 JSONL 报告到 targetContext.filesDir/dq_corner/report.jsonl。 */
object DqReport {
    fun append(context: Context, fields: Map<String, Any?>) {
        val dir = File(context.filesDir, "dq_corner").apply { mkdirs() }
        val obj = JSONObject()
        obj.put("ts", System.currentTimeMillis())
        for ((k, v) in fields) obj.put(k, v ?: JSONObject.NULL)
        File(dir, "report.jsonl").appendText(obj.toString() + "\n", Charsets.UTF_8)
    }
}

/** 列出主场景 wav（排除 _声纹 注册样本），按名排序。 */
fun mainWavs(testContext: Context): List<String> =
    testContext.assets.list("").orEmpty()
        .filter { it.endsWith(".wav", true) && !it.contains("声纹") }
        .sorted()

/** 对应主场景的 _声纹 注册样本名；找不到返回 null。 */
fun voiceprintSampleFor(testContext: Context, mainWav: String): String? {
    val prefix = mainWav.substringBefore('_').ifBlank { mainWav.substringBefore('.') }
    return testContext.assets.list("").orEmpty()
        .firstOrNull { it.contains("声纹") && it.startsWith(prefix) }
}
