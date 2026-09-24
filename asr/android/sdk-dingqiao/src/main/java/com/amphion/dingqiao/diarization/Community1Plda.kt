package com.amphion.dingqiao.diarization

import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.zip.ZipFile
import kotlin.math.sqrt
import kotlin.math.tanh

/**
 * Community-1 x-vector transform and PLDA scorer.  The files are NumPy 1.0
 * archives produced by pyannote; parsing them here keeps Python/NumPy out of
 * the Android runtime.
 */
internal class Community1Plda private constructor(
    private val mean1: FloatArray,
    private val lda: FloatArray,
    private val mean2: FloatArray,
    private val mu: FloatArray,
    private val psi: FloatArray,
    private val tr: FloatArray,
) {
    companion object {
        fun load(pldaFile: File, transformFile: File): Community1Plda {
            val plda = NpzReader(pldaFile)
            val transform = NpzReader(transformFile)
            return Community1Plda(
                transform.vector("mean1.npy", 256),
                transform.matrix("lda.npy", 256, 128),
                transform.vector("mean2.npy", 128),
                plda.vector("mu.npy", 128),
                plda.vector("psi.npy", 128),
                plda.matrix("tr.npy", 128, 128),
            )
        }
    }

    fun project(embedding: FloatArray): FloatArray? {
        if (embedding.size != mean1.size) return null
        val centered = FloatArray(embedding.size) { embedding[it] - mean1[it] }
        val result = FloatArray(mean2.size)
        for (row in result.indices) {
            var value = 0f
            // The exported matrix is [input, output], matching pyannote's
            // x-vector transform convention (output = lda.T @ centered).
            for (column in centered.indices) value += lda[column * mean2.size + row] * centered[column]
            result[row] = value - mean2[row]
        }
        val norm = sqrt(result.fold(0f) { total, value -> total + value * value })
        if (!norm.isFinite() || norm <= 1e-8f) return null
        for (i in result.indices) result[i] /= norm
        return result
    }

    /** Symmetric PLDA same-speaker score; larger values indicate a merge. */
    fun score(left: FloatArray, right: FloatArray): Float {
        if (left.size != 128 || right.size != 128) return Float.NEGATIVE_INFINITY
        var value = 0f
        var cosine = 0f
        val leftCentered = FloatArray(128) { left[it] - mu[it] }
        val rightCentered = FloatArray(128) { right[it] - mu[it] }
        for (i in 0 until 128) {
            val scale = psi[i] / (1f + psi[i]).coerceAtLeast(1e-5f)
            value += scale * leftCentered[i] * rightCentered[i]
            cosine += leftCentered[i] * rightCentered[i]
            for (j in 0 until 128) value += 0.5f * tr[i * 128 + j] * leftCentered[i] * rightCentered[j]
        }
        // The pyannote threshold is calibrated in a bounded affinity space;
        // retain that contract while adding the PLDA evidence.
        return (0.75f * cosine + 0.25f * ((tanh(value / 32f) + 1f) * .5f)).coerceIn(-1f, 1f)
    }
}

private class NpzReader(file: File) {
    private val entries = ZipFile(file).use { zip ->
        zip.entries().asSequence().associate { entry ->
            entry.name.substringAfterLast('/') to zip.getInputStream(entry).use { it.readBytes() }
        }
    }

    fun vector(name: String, size: Int): FloatArray {
        val values = read(name)
        require(values.size == size) { "$name expected $size values, got ${values.size}" }
        return values
    }

    fun matrix(name: String, rows: Int, columns: Int): FloatArray {
        val values = read(name)
        require(values.size == rows * columns) { "$name has invalid shape" }
        return values
    }

    private fun read(name: String): FloatArray {
        val bytes = entries[name] ?: error("missing $name in Community-1 archive")
        require(bytes.size >= 16 && bytes[0] == 0x93.toByte() &&
            bytes[1] == 'N'.code.toByte() && bytes[2] == 'U'.code.toByte() &&
            bytes[3] == 'M'.code.toByte() && bytes[4] == 'P'.code.toByte() &&
            bytes[5] == 'Y'.code.toByte()) {
            "$name is not a NumPy array"
        }
        val headerLength = ByteBuffer.wrap(bytes, 8, 2).order(ByteOrder.LITTLE_ENDIAN).short.toInt() and 0xffff
        val header = String(bytes, 10, headerLength, Charsets.US_ASCII)
        val count = Regex("shape': \\(?(\\d+)(?:, (\\d+))?").find(header)?.let {
            it.groupValues[1].toInt() * (it.groupValues[2].ifEmpty { "1" }.toInt())
        } ?: error("cannot parse $name shape")
        val isFloat64 = header.contains("<f8")
        val offset = 10 + headerLength
        val buffer = ByteBuffer.wrap(bytes, offset, bytes.size - offset).order(ByteOrder.LITTLE_ENDIAN)
        return FloatArray(count) { if (isFloat64) buffer.double.toFloat() else buffer.float }
    }
}
