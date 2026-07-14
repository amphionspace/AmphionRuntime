package com.amphion.dingqiao

internal object RejectedFinalLifecycle {
    fun completesSession(isLast: Boolean): Boolean = isLast
}
