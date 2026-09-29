package com.amphion.asr.internal

/** Internal adapter hook, dispatched after all ASR finals for this audio prefix. */
public interface ProcessedAudioObserver {
    public val audioProgressEnabled: Boolean
    public fun onAudioProcessed(endSample: Long)
}
