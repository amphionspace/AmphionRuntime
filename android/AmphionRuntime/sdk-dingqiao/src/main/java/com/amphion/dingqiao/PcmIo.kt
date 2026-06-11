package com.amphion.dingqiao

import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** PCM / WAV 读取，供声纹注册使用。 */
internal object PcmIo {

    private const val TARGET_SAMPLE_RATE = 16000

    fun readPcm16k(file: File): ShortArray {
        val name = file.name.lowercase()
        return when {
            name.endsWith(".wav") -> readWav16k(file)
            name.endsWith(".pcm") -> readRawPcm16k(file)
            else -> readWav16k(file).takeIf { it.isNotEmpty() } ?: readRawPcm16k(file)
        }
    }

    fun durationMs(sampleCount: Int, sampleRate: Int = TARGET_SAMPLE_RATE): Long =
        if (sampleRate <= 0) 0L else sampleCount.toLong() * 1000L / sampleRate

    fun shortsToFloats(pcm: ShortArray): FloatArray =
        FloatArray(pcm.size) { pcm[it] / 32768f }

    fun bytesToShortsLE(bytes: ByteArray): ShortArray {
        val count = bytes.size / 2
        val out = ShortArray(count)
        val buf = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        var i = 0
        while (i < count && buf.remaining() >= 2) {
            out[i++] = buf.short
        }
        return out
    }

    private fun readRawPcm16k(file: File): ShortArray = bytesToShortsLE(file.readBytes())

    private fun readWav16k(file: File): ShortArray {
        val bytes = file.readBytes()
        val info = parseWav(bytes) ?: return ShortArray(0)
        if (info.bitsPerSample != 16) return ShortArray(0)
        val pcm = decodePcm16(bytes, info)
        val mono = if (info.channels <= 1) pcm else downmixToMono(pcm, info.channels)
        return if (info.sampleRate == TARGET_SAMPLE_RATE) {
            mono
        } else {
            resampleLinear(mono, info.sampleRate, TARGET_SAMPLE_RATE)
        }
    }

    private data class WavInfo(
        val sampleRate: Int,
        val channels: Int,
        val bitsPerSample: Int,
        val pcmOffset: Int,
        val pcmBytes: Int,
    )

    private fun parseWav(bytes: ByteArray): WavInfo? {
        if (bytes.size < 44) return null
        val buf = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        if (buf.int != fourCc("RIFF")) return null
        buf.int
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
                    buf.int
                    buf.short
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
