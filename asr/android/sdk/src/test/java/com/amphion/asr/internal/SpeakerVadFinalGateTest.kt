package com.amphion.asr.internal

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SpeakerVadFinalGateTest {
    @Test
    fun speakerVadAloneStillScoresTheTerminalSpeech() {
        assertTrue(shouldScoreSpeakerFinal(false, true))
        assertTrue(shouldScoreSpeakerFinal(true, false))
        assertFalse(shouldScoreSpeakerFinal(false, false))
    }

    @Test
    fun shortTargetFinalUsesItsRealScoreWhenStreamingWindowDidNotConfirm() {
        assertFalse(shouldRejectSpeakerVadFinal(true, false, false, true))
        assertTrue(shouldRejectSpeakerVadFinal(true, false, false, false))
        assertTrue(shouldRejectSpeakerVadFinal(true, true, false, true))
    }
}
