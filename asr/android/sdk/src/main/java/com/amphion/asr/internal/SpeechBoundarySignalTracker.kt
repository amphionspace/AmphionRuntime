package com.amphion.asr.internal

/**
 * Tracks the public speech-event pair independently of Silero's current stream window.
 * ASR text/token is also speech evidence when Silero misses a quiet onset.
 * Decoder-thread confined.
 */
internal class SpeechBoundarySignalTracker {
    private var active = false

    /** Returns true only for the first confirmed speech signal in this public utterance. */
    fun observeSpeech(hasEvidence: Boolean = true): Boolean {
        if (!hasEvidence || active) return false
        active = true
        return true
    }

    /** A native, VAD, or speaker endpoint closes the public speech-event pair. */
    fun endpoint() {
        active = false
    }

    fun reset() {
        active = false
    }
}
