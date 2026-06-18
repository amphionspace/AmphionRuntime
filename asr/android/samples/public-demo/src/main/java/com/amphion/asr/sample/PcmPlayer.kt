package com.amphion.asr.sample

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack

/**
 * 极简 PCM 回放：AudioTrack STREAM 模式播一段 16-bit PCM。
 *
 * 与 [AudioRecorder] 对称，仅服务注册页试听。同一时刻只播一段，[play] 会先停掉上一段。
 * [onComplete] 在内部播放线程回调，调用方如需更新 UI 自行切主线程。
 */
internal class PcmPlayer {

    private var track: AudioTrack? = null
    private var thread: Thread? = null

    @Volatile
    private var playing = false

    fun isPlaying(): Boolean = playing

    fun play(pcm: ShortArray, sampleRate: Int = 16000, onComplete: () -> Unit) {
        stop()
        if (pcm.isEmpty()) {
            onComplete()
            return
        }
        val bufSize = AudioTrack.getMinBufferSize(
            sampleRate, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT,
        ).coerceAtLeast(4096)
        val t = AudioTrack.Builder()
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
            .setBufferSizeInBytes(bufSize)
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()
        track = t
        playing = true
        t.play()
        thread = Thread {
            var off = 0
            while (playing && off < pcm.size) {
                val n = t.write(pcm, off, minOf(pcm.size - off, 4096))
                if (n <= 0) break
                off += n
            }
            try {
                Thread.sleep(60)
            } catch (_: InterruptedException) {
            }
            playing = false
            try { t.stop() } catch (_: Throwable) {}
            try { t.release() } catch (_: Throwable) {}
            if (track === t) track = null
            onComplete()
        }.also { it.isDaemon = true; it.start() }
    }

    fun stop() {
        playing = false
        thread?.join(300)
        thread = null
        track?.let {
            try { it.stop() } catch (_: Throwable) {}
            try { it.release() } catch (_: Throwable) {}
        }
        track = null
    }
}
