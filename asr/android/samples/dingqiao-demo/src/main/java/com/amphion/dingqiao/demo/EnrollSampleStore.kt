package com.amphion.dingqiao.demo

import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

internal class EnrollSampleStore(private val dir: File) {

    init {
        dir.mkdirs()
    }

    fun listSamples(): List<File> =
        dir.listFiles { f -> f.isFile && f.name.endsWith(".wav") }
            ?.sortedBy { it.name }
            ?: emptyList()

    fun addSample(pcm: ShortArray): File {
        val f = File(dir, "sample_${System.currentTimeMillis()}.wav")
        WavIo.write(f, pcm)
        return f
    }

    fun deleteSample(file: File): Boolean = file.delete()

    fun readPcm(file: File): ShortArray {
        val bytes = file.readBytes()
        if (bytes.size < 44) return ShortArray(0)
        val buf = ByteBuffer.wrap(bytes, 44, bytes.size - 44).order(ByteOrder.LITTLE_ENDIAN)
        val count = (bytes.size - 44) / 2
        val out = ShortArray(count)
        var i = 0
        while (i < count && buf.remaining() >= 2) {
            out[i++] = buf.short
        }
        return out
    }
}
