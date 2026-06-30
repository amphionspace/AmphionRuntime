package com.amphion.dingqiao.demo

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.LinkedHashSet
import java.util.Locale

internal data class DebugRecordSummary(
    val baseName: String,
    val wavFile: File,
    val metaFile: File,
    val startTimeMs: Long,
    val endTimeMs: Long,
    val durationMs: Long,
    val sampleRate: Int,
    val status: String,
    val finalText: String,
    val lastPartial: String,
    val errorCode: Int?,
    val errorMessage: String?,
)

internal class DebugRecordStore(private val dir: File) {

    init {
        dir.mkdirs()
    }

    fun begin(): ActiveRecord {
        dir.mkdirs()
        val baseName = "rec_${FILE_NAME_FORMAT.format(Date())}"
        val wavFile = File(dir, "$baseName.wav")
        val metaFile = File(dir, "$baseName.json")
        return ActiveRecord(baseName, wavFile, metaFile)
    }

    fun listRecords(): List<DebugRecordSummary> =
        dir.listFiles { f -> f.isFile && f.name.endsWith(".json") }
            ?.mapNotNull { parseSummary(it) }
            ?.sortedByDescending { it.startTimeMs }
            ?: emptyList()

    fun readPcm(record: DebugRecordSummary): ShortArray = WavIo.readPcm(record.wavFile)

    private fun parseSummary(metaFile: File): DebugRecordSummary? {
        val obj = runCatching { JSONObject(metaFile.readText(Charsets.UTF_8)) }.getOrNull() ?: return null
        val baseName = obj.optString("baseName", metaFile.nameWithoutExtension)
        val wavFile = File(dir, obj.optString("wavFile", "$baseName.wav"))
        val startTimeMs = obj.optLong("startTimeMs", 0L)
        val endTimeMs = obj.optLong("endTimeMs", startTimeMs)
        val sampleRate = obj.optInt("sampleRate", SAMPLE_RATE)
        val durationMs = obj.optLong(
            "durationMs",
            wavDurationMs(wavFile, sampleRate),
        )
        val errorCode = if (obj.has("errorCode") && !obj.isNull("errorCode")) obj.optInt("errorCode") else null
        val errorMessage = if (obj.has("errorMessage") && !obj.isNull("errorMessage")) {
            obj.optString("errorMessage")
        } else {
            null
        }
        return DebugRecordSummary(
            baseName = baseName,
            wavFile = wavFile,
            metaFile = metaFile,
            startTimeMs = startTimeMs,
            endTimeMs = endTimeMs,
            durationMs = durationMs,
            sampleRate = sampleRate,
            status = obj.optString("status", STATUS_COMPLETED),
            finalText = obj.optString("finalText"),
            lastPartial = obj.optString("lastPartial"),
            errorCode = errorCode,
            errorMessage = errorMessage,
        )
    }

    private fun wavDurationMs(wavFile: File, sampleRate: Int): Long {
        val dataBytes = (wavFile.length() - WAV_HEADER_BYTES).coerceAtLeast(0L)
        return dataBytes * 1000L / (sampleRate * BYTES_PER_SAMPLE)
    }

    inner class ActiveRecord internal constructor(
        private val baseName: String,
        private val wavFile: File,
        private val metaFile: File,
    ) {
        private val startTimeMs = System.currentTimeMillis()
        private val sessionIds = LinkedHashSet<String>()
        private val finalResults = mutableListOf<FinalResult>()
        private var lastPartial = ""
        private var sampleCount = 0L
        private var closed = false
        private var writeError: String? = null
        private val wav = RandomAccessFile(wavFile, "rw").apply {
            setLength(0L)
            write(ByteArray(WAV_HEADER_BYTES))
        }

        @Synchronized
        fun addSession(sessionId: String) {
            if (sessionId.isNotBlank()) sessionIds += sessionId
        }

        @Synchronized
        fun updatePartial(text: String) {
            lastPartial = text
        }

        @Synchronized
        fun addFinal(text: String, speakerSimilarity: Float?) {
            if (text.isBlank()) return
            finalResults += FinalResult(text, speakerSimilarity)
            lastPartial = ""
        }

        @Synchronized
        fun appendPcm(samples: ShortArray) {
            if (closed || samples.isEmpty()) return
            try {
                wav.write(shortsToLittleEndian(samples))
                sampleCount += samples.size
            } catch (t: Throwable) {
                writeError = t.message ?: t.javaClass.simpleName
            }
        }

        @Synchronized
        fun finish(
            status: String,
            errorCode: Int? = null,
            errorMessage: String? = null,
        ): DebugRecordSummary? {
            if (closed) return null
            closed = true
            val endTimeMs = System.currentTimeMillis()
            val effectiveError = errorMessage ?: writeError
            runCatching {
                wav.seek(0L)
                wav.write(wavHeader(sampleCount * BYTES_PER_SAMPLE))
            }
            runCatching { wav.close() }

            val finalText = finalResults.joinToString(separator = "\n") { it.text }
            val durationMs = sampleCount * 1000L / SAMPLE_RATE
            val summary = DebugRecordSummary(
                baseName = baseName,
                wavFile = wavFile,
                metaFile = metaFile,
                startTimeMs = startTimeMs,
                endTimeMs = endTimeMs,
                durationMs = durationMs,
                sampleRate = SAMPLE_RATE,
                status = status,
                finalText = finalText,
                lastPartial = lastPartial,
                errorCode = errorCode,
                errorMessage = effectiveError,
            )
            runCatching { metaFile.writeText(toJson(summary, sessionIds, finalResults).toString(2), Charsets.UTF_8) }
            return summary
        }

        private fun shortsToLittleEndian(samples: ShortArray): ByteArray {
            val buf = ByteBuffer.allocate(samples.size * BYTES_PER_SAMPLE).order(ByteOrder.LITTLE_ENDIAN)
            for (sample in samples) buf.putShort(sample)
            return buf.array()
        }
    }

    private data class FinalResult(val text: String, val speakerSimilarity: Float?)

    private fun toJson(
        summary: DebugRecordSummary,
        sessionIds: Set<String>,
        finalResults: List<FinalResult>,
    ): JSONObject {
        val results = JSONArray()
        finalResults.forEach { result ->
            results.put(
                JSONObject()
                    .put("text", result.text)
                    .put("speakerSimilarity", result.speakerSimilarity ?: JSONObject.NULL),
            )
        }
        return JSONObject()
            .put("schemaVersion", 1)
            .put("baseName", summary.baseName)
            .put("wavFile", summary.wavFile.name)
            .put("startTimeMs", summary.startTimeMs)
            .put("endTimeMs", summary.endTimeMs)
            .put("durationMs", summary.durationMs)
            .put("sampleRate", summary.sampleRate)
            .put("channels", 1)
            .put("encoding", "PCM_16BIT")
            .put("status", summary.status)
            .put("errorCode", summary.errorCode ?: JSONObject.NULL)
            .put("errorMessage", summary.errorMessage ?: JSONObject.NULL)
            .put("sessionIds", JSONArray(sessionIds))
            .put("finalText", summary.finalText)
            .put("lastPartial", summary.lastPartial)
            .put("finalResults", results)
    }

    private fun wavHeader(dataBytes: Long): ByteArray {
        val buf = ByteBuffer.allocate(WAV_HEADER_BYTES).order(ByteOrder.LITTLE_ENDIAN)
        buf.put("RIFF".toByteArray(Charsets.US_ASCII))
        buf.putInt((36L + dataBytes).coerceAtMost(Int.MAX_VALUE.toLong()).toInt())
        buf.put("WAVE".toByteArray(Charsets.US_ASCII))
        buf.put("fmt ".toByteArray(Charsets.US_ASCII))
        buf.putInt(16)
        buf.putShort(1)
        buf.putShort(1)
        buf.putInt(SAMPLE_RATE)
        buf.putInt(SAMPLE_RATE * BYTES_PER_SAMPLE)
        buf.putShort(BYTES_PER_SAMPLE.toShort())
        buf.putShort(16)
        buf.put("data".toByteArray(Charsets.US_ASCII))
        buf.putInt(dataBytes.coerceAtMost(Int.MAX_VALUE.toLong()).toInt())
        return buf.array()
    }

    companion object {
        const val STATUS_COMPLETED = "completed"
        const val STATUS_ERROR = "error"
        const val STATUS_ABORTED = "aborted"

        private const val SAMPLE_RATE = 16_000
        private const val BYTES_PER_SAMPLE = 2
        private const val WAV_HEADER_BYTES = 44
        private val FILE_NAME_FORMAT = SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.US)
    }
}
