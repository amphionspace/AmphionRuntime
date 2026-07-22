package com.amphion.dingqiao.demo

internal class AsyncResourceRequestGate<T>(
    private val release: (T) -> Unit,
) {
    private val lock = Any()
    private var generation = 0L

    fun begin(): Long = synchronized(lock) { ++generation }

    fun invalidate() {
        synchronized(lock) { generation++ }
    }

    fun isCurrent(requestGeneration: Long): Boolean =
        synchronized(lock) { requestGeneration == generation }

    fun accept(requestGeneration: Long, resource: T): Boolean {
        if (isCurrent(requestGeneration)) return true
        release(resource)
        return false
    }
}
