package com.amphion.asr.internal

import androidx.annotation.Keep
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/**
 * Tracks sessions whose close work has been enqueued but whose decoder thread may still be using
 * engine-level native resources.
 *
 * A completed public session must not race the next session's native stream creation. Callers
 * therefore wait for every tracked decoder to become quiescent before crossing that boundary.
 */
@Keep
internal class ClosingSessionBarrier<T>(
    private val awaitQuiescent: (T, Long) -> Boolean,
    private val monotonicMs: () -> Long = { android.os.SystemClock.elapsedRealtime() },
) {
    private val lock = ReentrantLock()
    private val closing = LinkedHashSet<T>()

    fun track(value: T) {
        lock.withLock { closing.add(value) }
    }

    fun awaitAll(timeoutMs: Long): Boolean {
        require(timeoutMs >= 0L) { "timeoutMs must be non-negative" }
        val deadline = monotonicMs() + timeoutMs
        while (true) {
            val value = lock.withLock { closing.firstOrNull() } ?: return true
            val remaining = (deadline - monotonicMs()).coerceAtLeast(0L)
            if (remaining == 0L || !awaitQuiescent(value, remaining)) return false
            lock.withLock { closing.remove(value) }
        }
    }
}
