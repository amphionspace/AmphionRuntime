package com.lits.tts.sdk.internal

internal object FrontendTokenIds {
    fun withInitialSilence(ids: List<Int>, symbolToId: Map<String, Int>): LongArray {
        // New rhyme-body models were trained with a sentence-initial <sil>.
        // Legacy inventories have no such symbol and keep their existing IDs.
        val silence = symbolToId["<sil>"]
        val sequence = if (silence == null) ids else listOf(silence) + ids
        return sequence.map(Int::toLong).toLongArray()
    }
}
