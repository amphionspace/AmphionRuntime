package com.lits.tts.sample

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.os.SystemClock

internal class PcmPlayer {
    private var track: AudioTrack? = null
    private var thread: Thread? = null

    @Volatile
    private var playing = false

    fun play(pcm: ByteArray, sampleRate: Int, onComplete: () -> Unit) {
        stop()
        if (pcm.isEmpty()) {
            onComplete()
            return
        }
        val bufferSize = AudioTrack.getMinBufferSize(
            sampleRate,
            AudioFormat.CHANNEL_OUT_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        ).coerceAtLeast(4096)
        val localTrack = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build(),
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(sampleRate)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .build(),
            )
            .setBufferSizeInBytes(bufferSize)
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()
        track = localTrack
        playing = true
        localTrack.play()
        thread = Thread {
            var offset = 0
            while (playing && offset < pcm.size) {
                val written = localTrack.write(
                    pcm,
                    offset,
                    minOf(bufferSize, pcm.size - offset),
                    AudioTrack.WRITE_BLOCKING,
                )
                if (written <= 0) break
                offset += written
            }
            if (playing) {
                waitForPlaybackComplete(localTrack, offset / BYTES_PER_FRAME, sampleRate)
            }
            playing = false
            try {
                Thread.sleep(POST_DRAIN_GRACE_MS)
            } catch (_: InterruptedException) {
                Thread.currentThread().interrupt()
            }
            try {
                localTrack.stop()
            } catch (_: Throwable) {
            }
            try {
                localTrack.release()
            } catch (_: Throwable) {
            }
            if (track === localTrack) {
                track = null
            }
            onComplete()
        }.also {
            it.isDaemon = true
            it.start()
        }
    }

    fun stop() {
        playing = false
        thread?.join(300)
        thread = null
        track?.let { localTrack ->
            try {
                localTrack.stop()
            } catch (_: Throwable) {
            }
            try {
                localTrack.release()
            } catch (_: Throwable) {
            }
        }
        track = null
    }

    private fun waitForPlaybackComplete(localTrack: AudioTrack, targetFrames: Int, sampleRate: Int) {
        if (targetFrames <= 0) return
        val playbackBudgetMs = ((targetFrames * 1000L) / sampleRate).coerceAtLeast(50L)
        val deadlineAt = SystemClock.elapsedRealtime() + playbackBudgetMs + 500L
        while (playing && SystemClock.elapsedRealtime() < deadlineAt) {
            val playedFrames = localTrack.playbackHeadPosition
            if (playedFrames >= targetFrames) {
                return
            }
            val remainingFrames = (targetFrames - playedFrames).coerceAtLeast(1)
            val sleepMs = ((remainingFrames * 1000L) / sampleRate).coerceIn(5L, 20L)
            Thread.sleep(sleepMs)
        }
    }

    private companion object {
        const val BYTES_PER_FRAME = 2
        const val POST_DRAIN_GRACE_MS = 24L
    }
}
