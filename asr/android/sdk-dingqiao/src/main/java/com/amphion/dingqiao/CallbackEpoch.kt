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
    private val terminalClaimedEpoch = AtomicLong(NO_EPOCH)

    fun current(): Long = value.get()

    fun beginSession(): Long = value.incrementAndGet()

    fun invalidate(): Long = value.incrementAndGet()

    fun isCurrent(epoch: Long): Boolean = value.get() == epoch

    /**
     * Claims the one terminal callback allowed for [epoch]. The marker is epoch-bound rather than a
     * shared boolean, so a delayed old-session claim can never block a replacement session.
     */
    fun claimTerminal(epoch: Long): Boolean {
        while (isCurrent(epoch)) {
            val claimed = terminalClaimedEpoch.get()
            if (claimed == epoch) return false
            if (terminalClaimedEpoch.compareAndSet(claimed, epoch)) {
                return isCurrent(epoch)
            }
        }
        return false
    }

    private companion object {
        const val NO_EPOCH = Long.MIN_VALUE
    }
}

/** Tracks the synchronous callback phase so old completion cleanup cannot target a replacement. */
internal class CallbackInvocationContext {
    private val epoch = ThreadLocal<Long?>()

    fun isStaleForActiveSession(activeEpoch: Long, listening: Boolean): Boolean {
        val callbackEpoch = epoch.get() ?: return false
        return listening && callbackEpoch != activeEpoch
    }

    fun adopt(epoch: Long) {
        if (this.epoch.get() != null) this.epoch.set(epoch)
    }

    fun <T> withEpoch(callbackEpoch: Long, block: () -> T): T {
        val previous = epoch.get()
        epoch.set(callbackEpoch)
        return try {
            block()
        } finally {
            if (previous == null) epoch.remove() else epoch.set(previous)
        }
    }
}
