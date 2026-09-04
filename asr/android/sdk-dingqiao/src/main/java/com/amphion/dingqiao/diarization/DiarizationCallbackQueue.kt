package com.amphion.dingqiao.diarization

/** Enqueue while holding session state; drain outside it. Reentry cannot overtake earlier events. */
internal class DiarizationCallbackQueue {
    private val pending = java.util.ArrayDeque<() -> Unit>()
    private var draining = false
    private var closed = false

    @Synchronized fun enqueue(callback: () -> Unit) { if (!closed) pending.addLast(callback) }
    @Synchronized fun close() { closed = true; pending.clear() }

    fun drain() {
        synchronized(this) {
            if (draining || closed) return
            draining = true
        }
        while (true) {
            val callback = synchronized(this) {
                if (closed || pending.isEmpty()) {
                    draining = false
                    return
                }
                pending.removeFirst()
            }
            try { callback() } catch (error: Throwable) {
                synchronized(this) { draining = false }
                throw error
            }
        }
    }
}
