package com.amphion.asr.internal

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SpeakerVadFinalGateTest {
    @Test
    fun shortTargetFinalUsesItsRealScoreWhenStreamingWindowDidNotConfirm() {
        assertFalse(shouldRejectSpeakerVadFinal(true, false, false, true))
        assertTrue(shouldRejectSpeakerVadFinal(true, false, false, false))
        assertTrue(shouldRejectSpeakerVadFinal(true, true, false, true))
    }
}
