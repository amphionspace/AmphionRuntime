package com.amphion.dingqiao.diarization

internal data class DiarizationCommitBoundary(
    val beginTime: Int,
    val endTime: Int,
    val evidenceEndTime: Int,
)

internal class DiarizationCommitClock {
    private var plannedThrough = 0
    private var committedThrough = 0
    private val pending = java.util.ArrayDeque<DiarizationCommitBoundary>()

    fun observeEndpoint(endTime: Int) {
        if (endTime < plannedThrough + 120_000) return
        pending.add(DiarizationCommitBoundary(plannedThrough, endTime,
            ((endTime + 1500 + 2499) / 2500) * 2500))
        plannedThrough = endTime
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
