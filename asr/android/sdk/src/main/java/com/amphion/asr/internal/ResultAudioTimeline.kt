package com.amphion.asr.internal

import com.amphion.asr.AsrResult
import java.lang.ref.WeakReference

/** SDK-to-adapter metadata. Identity matching also distinguishes equal empty endpoint results. */
public object ResultAudioTimeline {
    private val endpoints = mutableListOf<Pair<WeakReference<AsrResult>, Long>>()

    @Synchronized
    public fun record(result: AsrResult, endSample: Long) {
        endpoints.removeAll { it.first.get() == null || it.first.get() === result }
        endpoints += WeakReference(result) to endSample
    }

    @Synchronized
    public fun endSample(result: AsrResult): Long? =
        endpoints.firstOrNull { it.first.get() === result }?.second

    @Synchronized
    internal fun transfer(source: AsrResult, destination: AsrResult) {
        if (source === destination) return
        endSample(source)?.let { record(destination, it) }
        endpoints.removeAll { it.first.get() === source }
    }
}
