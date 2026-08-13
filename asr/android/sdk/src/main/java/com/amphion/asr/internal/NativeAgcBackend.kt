package com.amphion.asr.internal

internal class NativeAgcBackend(sampleRate: Int) : AgcBackend {
    private var handle: Long = nativeCreate(sampleRate).also {
        check(it != 0L) { "failed to create WebRTC AGC2" }
    }

    override fun process(frame: FloatArray): FloatArray {
        check(handle != 0L) { "WebRTC AGC2 is closed" }
        return frame.copyOf().also { output ->
            check(nativeProcess(handle, output)) { "WebRTC AGC2 failed to process audio frame" }
        }
    }

    override fun close() {
        val current = handle
        if (current == 0L) return
        handle = 0L
        nativeDestroy(current)
    }

    private external fun nativeCreate(sampleRate: Int): Long
    private external fun nativeProcess(handle: Long, frame: FloatArray): Boolean
    private external fun nativeDestroy(handle: Long)

    private companion object {
        init {
            System.loadLibrary("amphion_audio_processing")
        }
    }
}
