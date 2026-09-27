package com.lits.tts.sample

import java.io.File

/** Whole-process resident memory; the peak is since process start, not per request. */
internal data class ProcessMemory(val rssKb: Long, val peakRssKb: Long) {
    companion object {
        fun read(): ProcessMemory? = runCatching {
            var rss: Long? = null
            var peak: Long? = null
            File("/proc/self/status").forEachLine { line ->
                when {
                    line.startsWith("VmRSS:") -> rss = line.substringAfter(':').trim().substringBefore(' ').toLong()
                    line.startsWith("VmHWM:") -> peak = line.substringAfter(':').trim().substringBefore(' ').toLong()
                }
            }
            ProcessMemory(requireNotNull(rss), requireNotNull(peak))
        }.getOrNull()
    }
}
