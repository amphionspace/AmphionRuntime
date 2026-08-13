package com.amphion.asr.internal

/**
 * Serializes caller-thread decoder submissions with terminal commands.
 *
 * The callback must only enqueue work and return quickly. Keeping the state transition and enqueue
 * under one lock guarantees that accepted PCM is ahead of stop, while PCM arriving after stop or
 * close is rejected before it can reach per-session native resources.
 */
internal class DecoderSubmissionFence {
    private enum class State { ACTIVE, STOPPED, CLOSED }

    private val lock = Any()
    private var state = State.ACTIVE

    fun submitActive(enqueue: () -> Unit): Boolean = synchronized(lock) {
        if (state != State.ACTIVE) return@synchronized false
        enqueue()
        true
    }

    fun submitStop(enqueue: () -> Unit): Boolean = synchronized(lock) {
        if (state != State.ACTIVE) return@synchronized false
        state = State.STOPPED
        enqueue()
        true
    }

    fun submitClose(enqueue: () -> Unit): Boolean = synchronized(lock) {
        if (state == State.CLOSED) return@synchronized false
        state = State.CLOSED
        enqueue()
        true
    }
}
