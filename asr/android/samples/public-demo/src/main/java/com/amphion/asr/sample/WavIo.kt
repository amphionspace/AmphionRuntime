package com.amphion.asr.sample

import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * 极简 16-bit PCM WAV 读写。
 *
 * [readPcm]：按 44 字节头解析（声纹注册自产自销）。
 * [readPcm16k]：读任意标准 PCM WAV，非 16 kHz 单声道时线性重采样到 16 kHz（KeSpeech 24 kHz）。
 */
internal object WavIo {

    private const val TARGET_SAMPLE_RATE = 16000

    data class WavInfo(
        val sampleRate: Int,
        val channels: Int,
        val bitsPerSample: Int,
        val pcmOffset: Int,
        val pcmBytes: Int,
    )

    fun write(file: File, pcm: ShortArray, sampleRate: Int = TARGET_SAMPLE_RATE) {
        val channels = 1
        val bitsPerSample = 16
        val byteRate = sampleRate * channels * bitsPerSample / 8
        val blockAlign = channels * bitsPerSample / 8
        val dataBytes = pcm.size * 2
        val buf = ByteBuffer.allocate(44 + dataBytes).order(ByteOrder.LITTLE_ENDIAN)
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

    fun readPcm(file: File): ShortArray = readPcm16k(file)

    /** 读 WAV 并保证输出 16 kHz 单声道 16-bit PCM（SDK 要求）。 */
    fun readPcm16k(file: File): ShortArray {
        val info = parseWav(file.readBytes()) ?: return ShortArray(0)
        if (info.bitsPerSample != 16) return ShortArray(0)
        val pcm = decodePcm16(file.readBytes(), info)
        val mono = if (info.channels <= 1) pcm else downmixToMono(pcm, info.channels)
        return if (info.sampleRate == TARGET_SAMPLE_RATE) {
            mono
        } else {
            resampleLinear(mono, info.sampleRate, TARGET_SAMPLE_RATE)
        }
    }

    fun durationMs(sampleCount: Int, sampleRate: Int = TARGET_SAMPLE_RATE): Long =
        if (sampleRate <= 0) 0L else sampleCount.toLong() * 1000L / sampleRate

    private fun parseWav(bytes: ByteArray): WavInfo? {
        if (bytes.size < 44) return null
        val buf = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        if (buf.int != fourCc("RIFF")) return null
        buf.int // chunk size
        if (buf.int != fourCc("WAVE")) return null

        var sampleRate = 0
        var channels = 0
        var bitsPerSample = 0
        var pcmOffset = -1
        var pcmBytes = 0

        while (buf.remaining() >= 8) {
            val id = buf.int
            val size = buf.int
            if (size < 0 || buf.remaining() < size) break
            when (id) {
                fourCc("fmt ") -> {
                    if (size < 16) return null
                    val fmtStart = buf.position()
                    val audioFormat = buf.short.toInt() and 0xffff
                    channels = buf.short.toInt() and 0xffff
                    sampleRate = buf.int
                    buf.int // byte rate
                    buf.short // block align
                    bitsPerSample = buf.short.toInt() and 0xffff
                    buf.position(fmtStart + size)
                    if (audioFormat != 1) return null
                }
                fourCc("data") -> {
                    pcmOffset = buf.position()
                    pcmBytes = size
                    buf.position(pcmOffset + size)
                }
                else -> buf.position(buf.position() + size)
            }
        }
        if (pcmOffset < 0 || sampleRate <= 0 || channels <= 0 || bitsPerSample <= 0) return null
        return WavInfo(sampleRate, channels, bitsPerSample, pcmOffset, pcmBytes)
    }

    private fun decodePcm16(bytes: ByteArray, info: WavInfo): ShortArray {
        val count = info.pcmBytes / 2
        val shorts = ShortArray(count)
        ByteBuffer.wrap(bytes, info.pcmOffset, info.pcmBytes)
            .order(ByteOrder.LITTLE_ENDIAN)
            .asShortBuffer()
            .get(shorts)
        return shorts
    }

    private fun downmixToMono(interleaved: ShortArray, channels: Int): ShortArray {
        if (channels <= 1) return interleaved
        val frames = interleaved.size / channels
        val out = ShortArray(frames)
        var i = 0
        var o = 0
        while (o < frames) {
            var sum = 0
            var c = 0
            while (c < channels) {
                sum += interleaved[i++].toInt()
                c++
            }
            out[o++] = (sum / channels).toShort()
        }
        return out
    }

    private fun resampleLinear(input: ShortArray, inRate: Int, outRate: Int): ShortArray {
        if (input.isEmpty() || inRate <= 0 || outRate <= 0) return ShortArray(0)
        if (inRate == outRate) return input
        val outLen = (input.size.toLong() * outRate / inRate).toInt().coerceAtLeast(1)
        val out = ShortArray(outLen)
        val ratio = input.size.toDouble() / outLen
        var i = 0
        while (i < outLen) {
            val pos = i * ratio
            val idx = pos.toInt().coerceIn(0, input.lastIndex)
            val frac = pos - idx
            val next = input[(idx + 1).coerceAtMost(input.lastIndex)].toInt()
            val v = input[idx].toInt() + ((next - input[idx].toInt()) * frac).toInt()
            out[i] = v.coerceIn(-32768, 32767).toShort()
            i++
        }
        return out
    }

    private fun fourCc(s: String): Int {
        val b = s.toByteArray(Charsets.US_ASCII)
        return (b[0].toInt() and 0xff) or
            ((b[1].toInt() and 0xff) shl 8) or
            ((b[2].toInt() and 0xff) shl 16) or
            ((b[3].toInt() and 0xff) shl 24)
    }
}
