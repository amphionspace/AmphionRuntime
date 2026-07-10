package com.lits.tts.sdk.internal

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.os.SystemClock
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.atomic.AtomicBoolean

internal class AndroidPcmPlayer {
    private val lock = Any()

    @Volatile
    private var track: AudioTrack? = null

    fun playBlocking(audio: SynthesizedAudio, cancelled: AtomicBoolean, soundChannel: Int?) {
        val minBufferSize = minBufferSize(audio.sampleRate)
        val localTrack = createTrack(audio.sampleRate, soundChannel, minBufferSize)
        synchronized(lock) {
            track = localTrack
        }
        try {
            localTrack.play()
            var offset = 0
            while (offset < audio.pcm.size && !cancelled.get()) {
                val length = minOf(minBufferSize, audio.pcm.size - offset)
                val written = localTrack.write(audio.pcm, offset, length, AudioTrack.WRITE_BLOCKING)
                if (written <= 0) break
                offset += written
            }
            if (!cancelled.get()) {
                waitForPlaybackComplete(
                    localTrack = localTrack,
                    targetFrames = offset / BYTES_PER_FRAME,
                    sampleRate = audio.sampleRate,
                    cancelled = cancelled,
                )
            }
        } finally {
            if (cancelled.get()) {
                releaseImmediately(localTrack)
            } else {
                releaseAfterDrain(localTrack)
            }
        }
    }

    fun playStreaming(
        sampleRate: Int,
        cancelled: AtomicBoolean,
        soundChannel: Int?,
        queueCapacity: Int = DEFAULT_STREAMING_QUEUE_CAPACITY,
        producer: ((ByteArray) -> Unit) -> Unit,
        onSynthesisComplete: () -> Unit = {},
        onFirstAudioWritten: () -> Unit = {},
    ) {
        val minBufferSize = minBufferSize(sampleRate)
        val localTrack = createTrack(sampleRate, soundChannel, minBufferSize)
        synchronized(lock) {
            track = localTrack
        }
        var totalBytes = 0
        val totalBytesLock = Object()
        val actualQueueCapacity = queueCapacity.coerceIn(1, MAX_STREAMING_QUEUE_CAPACITY)
        val prebufferChunks = minOf(STREAMING_PREBUFFER_CHUNKS, actualQueueCapacity)
        val audioQueue = LinkedBlockingQueue<ByteArray>(actualQueueCapacity)
        val playbackError = arrayOfNulls<Throwable>(1)
        val producerError = arrayOfNulls<Throwable>(1)
        val prebufferLock = Object()
        var queuedChunks = 0
        var producerFinished = false
        val firstAudioWritten = AtomicBoolean(false)
        val playbackThread = Thread(
            {
                try {
                    while (!cancelled.get()) {
                        val chunk = audioQueue.take()
                        if (chunk === END_OF_STREAM) return@Thread
                        var offset = 0
                        while (offset < chunk.size && !cancelled.get()) {
                            val length = minOf(minBufferSize, chunk.size - offset)
                            val written = localTrack.write(chunk, offset, length, AudioTrack.WRITE_BLOCKING)
                            if (written <= 0) break
                            if (firstAudioWritten.compareAndSet(false, true)) {
                                onFirstAudioWritten()
                            }
                            offset += written
                            synchronized(totalBytesLock) {
                                totalBytes += written
                            }
                        }
                    }
                } catch (interrupted: InterruptedException) {
                    Thread.currentThread().interrupt()
                } catch (error: Throwable) {
                    playbackError[0] = error
                    cancelled.set(true)
                }
            },
            "lits-tts-pcm-playback",
        ).apply { isDaemon = true }
        val producerThread = Thread(
            {
                try {
                    producer { chunk ->
                        if (!cancelled.get()) {
                            audioQueue.put(chunk.copyOf())
                            synchronized(prebufferLock) {
                                queuedChunks += 1
                                prebufferLock.notifyAll()
                            }
                        }
                    }
                    onSynthesisComplete()
                } catch (interrupted: InterruptedException) {
                    Thread.currentThread().interrupt()
                } catch (error: Throwable) {
                    producerError[0] = error
                    cancelled.set(true)
                } finally {
                    synchronized(prebufferLock) {
                        producerFinished = true
                        prebufferLock.notifyAll()
                    }
                    audioQueue.offer(END_OF_STREAM)
                }
            },
            "lits-tts-pcm-producer",
        ).apply { isDaemon = true }
        try {
            producerThread.start()
            waitForStreamingPrebuffer(prebufferLock) {
                cancelled.get() || producerFinished || queuedChunks >= prebufferChunks
            }
            localTrack.play()
            playbackThread.start()
            joinUntilFinishedOrCancelled(producerThread, cancelled)
            joinUntilFinishedOrCancelled(playbackThread, cancelled)
            producerError[0]?.let { throw it }
            playbackError[0]?.let { throw it }
            if (!cancelled.get()) {
                val writtenBytes = synchronized(totalBytesLock) { totalBytes }
                waitForPlaybackComplete(
                    localTrack = localTrack,
                    targetFrames = writtenBytes / BYTES_PER_FRAME,
                    sampleRate = sampleRate,
                    cancelled = cancelled,
                )
            }
        } finally {
            audioQueue.offer(END_OF_STREAM)
            if (producerThread.isAlive) {
                producerThread.interrupt()
                if (!cancelled.get()) {
                    producerThread.join(PLAYBACK_THREAD_JOIN_TIMEOUT_MS)
                }
            }
            if (playbackThread.isAlive) {
                playbackThread.interrupt()
                if (!cancelled.get()) {
                    playbackThread.join(PLAYBACK_THREAD_JOIN_TIMEOUT_MS)
                }
            }
            if (cancelled.get()) {
                releaseImmediately(localTrack)
            } else {
                releaseAfterDrain(localTrack)
            }
        }
    }

    private fun joinUntilFinishedOrCancelled(thread: Thread, cancelled: AtomicBoolean) {
        while (thread.isAlive && !cancelled.get()) {
            thread.join(STREAMING_THREAD_JOIN_POLL_MS)
        }
    }

    @Suppress("PLATFORM_CLASS_MAPPED_TO_KOTLIN")
    private fun waitForStreamingPrebuffer(lock: Object, ready: () -> Boolean) {
        synchronized(lock) {
            while (!ready()) {
                lock.wait(STREAMING_PREBUFFER_WAIT_MS)
            }
        }
    }

    internal fun buildAudioAttributes(soundChannel: Int?): AudioAttributes {
        val builder = AudioAttributes.Builder()
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
        if (soundChannel != null) {
            builder.setLegacyStreamType(soundChannel)
        } else {
            builder.setUsage(AudioAttributes.USAGE_MEDIA)
        }
        return builder.build()
    }

    fun stop() {
        synchronized(lock) {
            track?.let(::releaseImmediately)
            track = null
        }
    }

    private fun minBufferSize(sampleRate: Int): Int = AudioTrack.getMinBufferSize(
        sampleRate,
        AudioFormat.CHANNEL_OUT_MONO,
        AudioFormat.ENCODING_PCM_16BIT,
    ).coerceAtLeast(4096)

    private fun createTrack(sampleRate: Int, soundChannel: Int?, minBufferSize: Int): AudioTrack {
        return AudioTrack.Builder()
            .setAudioAttributes(buildAudioAttributes(soundChannel))
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(sampleRate)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .build(),
            )
            .setBufferSizeInBytes(minBufferSize)
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()
    }

    private fun waitForPlaybackComplete(
        localTrack: AudioTrack,
        targetFrames: Int,
        sampleRate: Int,
        cancelled: AtomicBoolean,
    ) {
        if (targetFrames <= 0) return
        val playbackBudgetMs = ((targetFrames * 1000L) / sampleRate).coerceAtLeast(50L)
        val deadlineAt = SystemClock.elapsedRealtime() + playbackBudgetMs + 500L
        while (!cancelled.get() && SystemClock.elapsedRealtime() < deadlineAt) {
            val playedFrames = localTrack.playbackHeadPosition
            if (playedFrames >= targetFrames) {
                return
            }
            val remainingFrames = (targetFrames - playedFrames).coerceAtLeast(1)
            val sleepMs = ((remainingFrames * 1000L) / sampleRate).coerceIn(5L, 20L)
            Thread.sleep(sleepMs)
        }
    }

    private fun releaseImmediately(localTrack: AudioTrack) {
        try {
            localTrack.pause()
        } catch (_: Throwable) {
        }
        try {
            localTrack.flush()
        } catch (_: Throwable) {
        }
        releaseAfterDrain(localTrack)
    }

    private fun releaseAfterDrain(localTrack: AudioTrack) {
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
        synchronized(lock) {
            if (track === localTrack) {
                track = null
            }
        }
    }

    private companion object {
        const val BYTES_PER_FRAME = 2
        const val POST_DRAIN_GRACE_MS = 24L
        const val PLAYBACK_THREAD_JOIN_TIMEOUT_MS = 200L
        const val STREAMING_THREAD_JOIN_POLL_MS = 20L
        const val DEFAULT_STREAMING_QUEUE_CAPACITY = 32
        const val MAX_STREAMING_QUEUE_CAPACITY = 256
        const val STREAMING_PREBUFFER_CHUNKS = 1
        const val STREAMING_PREBUFFER_WAIT_MS = 20L
        val END_OF_STREAM = ByteArray(0)
    }
}
