package com.amphion.asr.internal

import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/** Bounds PCM retained by caller-to-decoder submissions without changing submission order. */
internal class PcmSubmissionLimiter(
    private val maxPendingSamples: Int,
) {
    private val lock = ReentrantLock()
    private val capacityAvailable = lock.newCondition()
    private var accepting = true
    private var pendingSamples = 0

    init {
        require(maxPendingSamples > 0) { "maxPendingSamples must be positive" }
    }

    fun reserve(sampleCount: Int): Boolean {
        require(sampleCount in 1..maxPendingSamples) {
            "sampleCount must be between 1 and $maxPendingSamples"
        }
        lock.withLock {
            while (accepting && pendingSamples + sampleCount > maxPendingSamples) {
                capacityAvailable.awaitUninterruptibly()
            }
            if (!accepting) return false
            pendingSamples += sampleCount
            return true
        }
    }

    fun release(sampleCount: Int) {
        lock.withLock {
            pendingSamples = (pendingSamples - sampleCount).coerceAtLeast(0)
            capacityAvailable.signalAll()
        }
    }

    fun stopAccepting() {
        lock.withLock {
            accepting = false
            capacityAvailable.signalAll()
        }
    }
}
