package com.amphion.dingqiao.demo

import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

internal object WavIo {

    fun write(file: File, pcm: ShortArray, sampleRate: Int = 16000) {
        val dataBytes = pcm.size * 2
        val buf = ByteBuffer.allocate(44 + dataBytes).order(ByteOrder.LITTLE_ENDIAN)
        buf.put("RIFF".toByteArray(Charsets.US_ASCII))
        buf.putInt(36 + dataBytes)
        buf.put("WAVE".toByteArray(Charsets.US_ASCII))
        buf.put("fmt ".toByteArray(Charsets.US_ASCII))
        buf.putInt(16)
        buf.putShort(1)
        buf.putShort(1)
        buf.putInt(sampleRate)
        buf.putInt(sampleRate * 2)
        buf.putShort(2)
        buf.putShort(16)
        buf.put("data".toByteArray(Charsets.US_ASCII))
        buf.putInt(dataBytes)
        for (s in pcm) buf.putShort(s)
        file.parentFile?.mkdirs()
        file.writeBytes(buf.array())
    }

    fun writePcmBytes(file: File, pcm: ByteArray, sampleRate: Int = 16000) {
        require(pcm.size % 2 == 0) { "PCM byte length must be even: ${pcm.size}" }
        val buf = ByteBuffer.allocate(44 + pcm.size).order(ByteOrder.LITTLE_ENDIAN)
        buf.put("RIFF".toByteArray(Charsets.US_ASCII))
        buf.putInt(36 + pcm.size)
        buf.put("WAVE".toByteArray(Charsets.US_ASCII))
        buf.put("fmt ".toByteArray(Charsets.US_ASCII))
        buf.putInt(16)
        buf.putShort(1)
        buf.putShort(1)
        buf.putInt(sampleRate)
        buf.putInt(sampleRate * 2)
        buf.putShort(2)
        buf.putShort(16)
        buf.put("data".toByteArray(Charsets.US_ASCII))
        buf.putInt(pcm.size)
        buf.put(pcm)
        file.parentFile?.mkdirs()
        file.writeBytes(buf.array())
    }

    /** File-input diagnostics accept only actual 20 ms PCM frames, without synthetic padding. */
    fun readDemoInput(file: File): ByteArray {
        val bytes = file.readBytes()
        val buf = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        fun tag(offset: Int) = String(bytes, offset, 4, Charsets.US_ASCII)
        require(bytes.size >= 44 && tag(0) == "RIFF" && tag(8) == "WAVE") { "需要 WAV 文件" }
        var offset = 12
        var validFormat = false
        var pcm: ByteArray? = null
        while (offset + 8 <= bytes.size) {
            val size = buf.getInt(offset + 4)
            val start = offset + 8
            require(size >= 0 && size <= bytes.size - start) { "WAV 数据不完整" }
            when (tag(offset)) {
                "fmt " -> {
                    require(size >= 16) { "WAV 格式不完整" }
                    validFormat = buf.getShort(start).toInt() == 1 &&
                        buf.getShort(start + 2).toInt() == 1 && buf.getInt(start + 4) == 16000 &&
                        buf.getShort(start + 12).toInt() == 2 && buf.getShort(start + 14).toInt() == 16
                }
                "data" -> pcm = bytes.copyOfRange(start, start + size)
            }
            offset = start + size + (size and 1)
        }
        require(validFormat) { "需要 16kHz 单声道 PCM16 WAV" }
        val data = requireNotNull(pcm) { "WAV 缺少音频" }
        require(data.isNotEmpty() && data.size % 640 == 0) { "音频时长需要对齐 20ms" }
        return data
    }

    fun readPcmBytes(file: File): ByteArray {
        val bytes = file.readBytes()
        if (bytes.size < WAV_HEADER_BYTES) return ByteArray(0)
        val dataOffset = dataOffset(bytes)
        if (dataOffset < 0 || dataOffset >= bytes.size) return ByteArray(0)
        return bytes.copyOfRange(dataOffset, bytes.size)
    }

    fun readPcm(file: File): ShortArray {
        val bytes = readPcmBytes(file)
        val buf = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        val count = bytes.size / 2
        val out = ShortArray(count)
        var i = 0
        while (i < count && buf.remaining() >= 2) {
            out[i++] = buf.short
        }
        return out
    }

    fun durationLabel(sampleCount: Int, sampleRate: Int = 16000): String {
        val sec = sampleCount.toFloat() / sampleRate
        return "%.1fs".format(sec)
    }

    private fun dataOffset(bytes: ByteArray): Int {
        var i = 12
        while (i + 8 <= bytes.size) {
            val id = String(bytes, i, 4, Charsets.US_ASCII)
            val size = ByteBuffer.wrap(bytes, i + 4, 4).order(ByteOrder.LITTLE_ENDIAN).int
            val dataStart = i + 8
            if (id == "data") return dataStart
            i = dataStart + size.coerceAtLeast(0)
        }
        return if (bytes.size >= WAV_HEADER_BYTES) WAV_HEADER_BYTES else -1
    }

    private const val WAV_HEADER_BYTES = 44
}
