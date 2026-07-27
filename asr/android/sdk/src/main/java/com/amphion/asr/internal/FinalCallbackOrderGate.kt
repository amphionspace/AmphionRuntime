package com.amphion.asr.internal

/**
 * Keeps the normal session completion callback behind every final that has entered post-processing.
 *
 * The decoder and post-processor run on different threads, so decoder drain completion alone does
 * not mean that the corresponding final has been enqueued on the callback thread.
 */
internal class FinalCallbackOrderGate {
    private var pendingFinals: Int = 0
    private var stoppedRequested: Boolean = false
    private var stoppedGranted: Boolean = false

    @Synchronized
    fun onFinalQueued() {
        check(!stoppedGranted) { "cannot queue a final after stopped callback was granted" }
        pendingFinals += 1
    }

    /**
     * Called only after the final callback has been enqueued on the serial callback handler.
     * Returns true exactly once when the stopped callback may now be enqueued behind it.
     */
    @Synchronized
    fun onFinalEnqueued(): Boolean {
        check(pendingFinals > 0) { "final callback enqueued without a queued final" }
        pendingFinals -= 1
        return grantStoppedIfReady()
    }

    /**
     * Records normal decoder completion. Returns true when there are no pending final callbacks.
     */
    @Synchronized
    fun requestStopped(): Boolean {
        stoppedRequested = true
        return grantStoppedIfReady()
    }

    private fun grantStoppedIfReady(): Boolean {
        if (!stoppedRequested || pendingFinals != 0 || stoppedGranted) return false
        stoppedGranted = true
        return true
    }
}
