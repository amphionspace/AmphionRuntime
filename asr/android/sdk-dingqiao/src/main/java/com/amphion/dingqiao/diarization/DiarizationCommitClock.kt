package com.amphion.dingqiao.diarization

internal data class DiarizationCommitBoundary(val beginTime: Int, val endTime: Int, val evidenceEndTime: Int)

/** Decisions use processed audio time, independently of native inference latency. */
internal class DiarizationCommitClock {
    private var plannedThrough = 0
    private var committedThrough = 0
    private var processedThrough = 0
    private val endpoints = mutableListOf<Int>()
    private val pending = java.util.ArrayDeque<DiarizationCommitBoundary>()

    fun observeEndpoint(endTime: Int) {
        if (endTime > plannedThrough && endTime > (endpoints.lastOrNull() ?: 0)) endpoints += endTime
    }

    fun observeProcessedAudio(endTime: Int): Boolean {
        processedThrough = maxOf(processedThrough, endTime)
        var queued = false
        while (processedThrough >= plannedThrough + 120_000) {
            val deadline = plannedThrough + 120_000
            var boundary: Int? = null
            for (endpoint in endpoints) {
                if (endpoint <= deadline) boundary = endpoint
                else { if (boundary == null) boundary = endpoint; break }
            }
            val end = boundary ?: break
            if (end > processedThrough) break
            pending += DiarizationCommitBoundary(plannedThrough, end,
                ((maxOf(deadline, end) + 1500 + 2499) / 2500) * 2500)
            plannedThrough = end
            endpoints.removeAll { it <= end }
            queued = true
        }
        return queued
    }

    fun takeReady(inferenceEndTime: Int): DiarizationCommitBoundary? {
        val next = pending.peekFirst() ?: return null
        if (inferenceEndTime < next.evidenceEndTime) return null
        pending.removeFirst()
        committedThrough = next.endTime
        return next
    }
    fun beginTime(): Int = committedThrough
}
