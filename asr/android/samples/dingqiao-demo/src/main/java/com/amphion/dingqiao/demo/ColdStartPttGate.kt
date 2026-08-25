package com.amphion.dingqiao.demo

data class ColdStartEngineDecision(
    val accepted: Boolean,
    val finishAfterFlush: Boolean,
)

/** Coordinates PTT release, recorder-tail flush, and asynchronous model load. */
class ColdStartPttGate {
    private var generation = 0
    private var activeGeneration = -1
    private var released = false
    private var captureDrained = false
    private var ready = false

    @Synchronized
    fun begin(): Int {
        generation += 1
        activeGeneration = generation
        released = false
        captureDrained = false
        ready = false
        return activeGeneration
    }

    @Synchronized
    fun release(requestGeneration: Int): Boolean {
        if (requestGeneration != activeGeneration) return false
        released = true
        return true
    }

    @Synchronized
    fun captureStopped(requestGeneration: Int): Boolean {
        if (requestGeneration != activeGeneration) return false
        captureDrained = true
        return claimFinish()
    }

    @Synchronized
    fun engineReady(requestGeneration: Int): ColdStartEngineDecision {
        if (requestGeneration != activeGeneration) {
            return ColdStartEngineDecision(accepted = false, finishAfterFlush = false)
        }
        ready = true
        return ColdStartEngineDecision(accepted = true, finishAfterFlush = claimFinish())
    }

    @Synchronized
    fun cancel() {
        generation += 1
        activeGeneration = -1
        released = false
        captureDrained = false
        ready = false
    }

    private fun claimFinish(): Boolean {
        if (!released || !captureDrained || !ready) return false
        activeGeneration = -1
        return true
    }
}
