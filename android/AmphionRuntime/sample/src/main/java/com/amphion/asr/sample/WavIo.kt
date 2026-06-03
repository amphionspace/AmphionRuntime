package com.amphion.asr.sample

import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * 极简 16 kHz / 单声道 / 16-bit PCM WAV 读写。
 *
 * 仅服务声纹注册场景：写出的文件总是标准 44 字节头，读取也按 44 字节头解析
 * （自产自销，不处理任意第三方 WAV 的扩展 chunk）。
 */
internal object WavIo {

    private const val HEADER_SIZE = 44

    fun write(file: File, pcm: ShortArray, sampleRate: Int = 16000) {
        val channels = 1
        val bitsPerSample = 16
        val byteRate = sampleRate * channels * bitsPerSample / 8
        val blockAlign = channels * bitsPerSample / 8
        val dataBytes = pcm.size * 2
        val buf = ByteBuffer.allocate(HEADER_SIZE + dataBytes).order(ByteOrder.LITTLE_ENDIAN)
        buf.put("RIFF".toByteArray(Charsets.US_ASCII))
        buf.putInt(36 + dataBytes)
        buf.put("WAVE".toByteArray(Charsets.US_ASCII))
        buf.put("fmt ".toByteArray(Charsets.US_ASCII))
        buf.putInt(16)
        buf.putShort(1) // PCM
        buf.putShort(channels.toShort())
        buf.putInt(sampleRate)
        buf.putInt(byteRate)
        buf.putShort(blockAlign.toShort())
        buf.putShort(bitsPerSample.toShort())
        buf.put("data".toByteArray(Charsets.US_ASCII))
        buf.putInt(dataBytes)
        for (s in pcm) buf.putShort(s)
        file.parentFile?.mkdirs()
        file.writeBytes(buf.array())
    }

    fun readPcm(file: File): ShortArray {
        val bytes = file.readBytes()
        if (bytes.size <= HEADER_SIZE) return ShortArray(0)
        val dataLen = bytes.size - HEADER_SIZE
        val shorts = ShortArray(dataLen / 2)
        ByteBuffer.wrap(bytes, HEADER_SIZE, dataLen)
            .order(ByteOrder.LITTLE_ENDIAN)
            .asShortBuffer()
            .get(shorts)
        return shorts
    }

    fun durationMs(sampleCount: Int, sampleRate: Int = 16000): Long =
        if (sampleRate <= 0) 0L else sampleCount.toLong() * 1000L / sampleRate
}
