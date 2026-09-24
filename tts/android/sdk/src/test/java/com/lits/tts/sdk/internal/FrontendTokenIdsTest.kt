package com.lits.tts.sdk.internal

import org.junit.Assert.assertArrayEquals
import org.junit.Test

class FrontendTokenIdsTest {
    @Test
    fun legacyInventoryKeepsIdsWithoutBlankInsertion() {
        assertArrayEquals(longArrayOf(4, 5, 6), FrontendTokenIds.withInitialSilence(
            listOf(4, 5, 6), mapOf("<blank>" to 0, "<eos>" to 1)))
    }

    @Test
    fun rhymeBodyInventoryPrependsTrainingSilenceExactlyOnce() {
        assertArrayEquals(longArrayOf(1, 25, 66, 70), FrontendTokenIds.withInitialSilence(
            listOf(25, 66, 70), mapOf("<blank>" to 0, "<sil>" to 1)))
    }
}
