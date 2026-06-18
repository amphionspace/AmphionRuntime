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

    fun durationLabel(sampleCount: Int, sampleRate: Int = 16000): String {
        val sec = sampleCount.toFloat() / sampleRate
        return "%.1fs".format(sec)
    }
}
