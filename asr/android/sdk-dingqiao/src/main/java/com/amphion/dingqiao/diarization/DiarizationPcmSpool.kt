package com.amphion.dingqiao.diarization

import java.io.File
import java.io.RandomAccessFile

internal class DiarizationPcmSpool(private val directory: File) {
    var endOffset: Long = 0
        private set
    private var firstChunk = 0L
    private var writer: RandomAccessFile? = null

    fun append(audio: ByteArray) {
        var offset = 0
        while (offset < audio.size) {
            val chunk = endOffset / CHUNK_BYTES
            val position = (endOffset % CHUNK_BYTES).toInt()
            val output = writer ?: RandomAccessFile(path(chunk), "rw").also { writer = it }
            val count = minOf(audio.size - offset, CHUNK_BYTES - position)
            output.write(audio, offset, count)
            endOffset += count
            offset += count
            if (endOffset % CHUNK_BYTES == 0L) close()
        }
    }

    fun read(offsetBytes: Long, count: Int): ByteArray {
        val result = ByteArray(count)
        var copied = 0
        while (copied < count) {
            val absolute = offsetBytes + copied
            val position = absolute % CHUNK_BYTES
            val take = minOf(count - copied, CHUNK_BYTES - position.toInt())
            RandomAccessFile(path(absolute / CHUNK_BYTES), "r").use {
                it.seek(position)
                it.readFully(result, copied, take)
            }
            copied += take
        }
        return result
    }

    fun discardBefore(offsetBytes: Long) {
        val until = minOf(offsetBytes, endOffset) / CHUNK_BYTES
        while (firstChunk < until) {
            check(path(firstChunk).delete()) { "cannot remove consumed diarization PCM block" }
            firstChunk++
        }
    }

    fun close() { writer?.close(); writer = null }
    fun remove() {
        close()
        discardBefore(endOffset)
        if (endOffset % CHUNK_BYTES != 0L) check(path(firstChunk).delete())
    }
    private fun path(chunk: Long) = File(directory, "pcm-$chunk.bin")
    private companion object { const val CHUNK_BYTES = 16000 * 2 * 10 }
}
