package com.amphion.dingqiao

import java.util.concurrent.atomic.AtomicLong

/**
 * Ownership token for asynchronously delivered customer callbacks.
 *
 * Advancing the epoch at every session replacement and shutdown makes queued work from an older
 * state self-discard, including when a caller intentionally reuses the same session ID.
 */
internal class CallbackEpoch {
    private val value = AtomicLong(0L)

    fun current(): Long = value.get()

    fun beginSession(): Long = value.incrementAndGet()

    fun invalidate(): Long = value.incrementAndGet()

    fun isCurrent(epoch: Long): Boolean = value.get() == epoch

    /**
     * Runs terminal follow-up only if customer callback reentry did not replace the owning state.
     */
    fun invokeThenIfCurrent(
        epoch: Long,
        callback: () -> Unit,
        followUp: () -> Unit,
    ): Boolean {
        if (!isCurrent(epoch)) return false
        try {
            callback()
        } finally {
            if (isCurrent(epoch)) followUp()
        }
        return true
    }
}
