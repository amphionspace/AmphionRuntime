package com.amphion.dingqiao.diarization

import java.io.File
import java.io.FileOutputStream
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

internal class DiarizationEvidence(
    val segments: FloatArray,
    val embeddings: FloatArray,
    val runEmbeddings: FloatArray,
    val runRanges: FloatArray,
    val runRms: FloatArray,
)

/** Lossless session evidence, as on Harmony. Public transcript commits cannot discard model inputs. */
internal class DiarizationEvidenceSpool(directory: File) {
    private val segmentFile = File(directory, "segments.f32")
    private val embeddingFile = File(directory, "embeddings.f32")
    private val runEmbeddingFile = File(directory, "run-embeddings.f32")
    private val runRangeFile = File(directory, "run-ranges.f32")
    private val runRmsFile = File(directory, "run-rms.f32")
    private val writers = mutableMapOf<File, FileOutputStream>()
    private val runCounts = mutableListOf<Int>()
    var windows = 0
        private set

    fun append(segments: FloatArray, embeddings: FloatArray, runEmbeddings: FloatArray = FloatArray(0),
        runRanges: FloatArray = FloatArray(0), runRms: FloatArray = FloatArray(0)) {
        require(segments.size == 589 * 3 && embeddings.size == 3 * 256) { "invalid diarization evidence shape" }
        require(runRanges.size % 4 == 0 && runEmbeddings.size == runRanges.size / 4 * 256 &&
            runRms.size == runRanges.size / 4) { "invalid diarization run evidence shape" }
        write(segmentFile, segments)
        write(embeddingFile, embeddings)
        write(runEmbeddingFile, runEmbeddings)
        write(runRangeFile, runRanges)
        write(runRmsFile, runRms)
        runCounts += runRanges.size / 4
        windows++
    }

    fun read(windowCount: Int): DiarizationEvidence {
        require(windowCount in 0..windows) { "diarization evidence snapshot exceeds completed windows" }
        writers.values.forEach { it.flush() }
        val runs = runCounts.take(windowCount).sum()
        val ranges = readFloats(runRangeFile, runs * 4)
        var offset = 0
        for (window in 0 until windowCount) {
            for (run in 0 until runCounts[window]) ranges[offset + run * 4] = window.toFloat()
            offset += runCounts[window] * 4
        }
        return DiarizationEvidence(readFloats(segmentFile, windowCount * 589 * 3),
            readFloats(embeddingFile, windowCount * 3 * 256), readFloats(runEmbeddingFile, runs * 256),
            ranges, readFloats(runRmsFile, runs))
    }

    fun close() {
        writers.values.forEach { runCatching { it.close() } }
        writers.clear()
    }

    fun remove() {
        close()
        listOf(segmentFile, embeddingFile, runEmbeddingFile, runRangeFile, runRmsFile).forEach { it.delete() }
    }

    private fun write(file: File, values: FloatArray) {
        if (values.isEmpty()) return
        val bytes = ByteBuffer.allocate(values.size * 4).order(ByteOrder.LITTLE_ENDIAN)
        bytes.asFloatBuffer().put(values)
        writers.getOrPut(file) { FileOutputStream(file, true) }.write(bytes.array())
    }

    private fun readFloats(file: File, count: Int): FloatArray {
        val result = FloatArray(count)
        if (count == 0) return result
        val bytes = ByteArray(count * 4)
        RandomAccessFile(file, "r").use { it.readFully(bytes) }
        ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer().get(result)
        return result
    }
}
