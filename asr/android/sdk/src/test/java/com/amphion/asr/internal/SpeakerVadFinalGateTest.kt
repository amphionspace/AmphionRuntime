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

    @Test
    fun targetSpeakerAloneRunsTheTurnDetectorSoASpeakerSwitchCanBeSplit() {
        // 缺陷 #87：只开机主识别、两人无缝接话时，没有流式检测就只剩整段一个分。
        assertTrue(shouldRunSpeakerTurnDetection(false, true, true, true))
        assertTrue(shouldRunSpeakerTurnDetection(true, false, false, true))
        assertTrue(shouldRunSpeakerTurnDetection(true, true, true, true))
    }

    @Test
    fun turnDetectorStaysOffWithoutAnEnrolledTargetOrWindowConfig() {
        assertFalse(shouldRunSpeakerTurnDetection(false, false, true, true))
        assertFalse(shouldRunSpeakerTurnDetection(false, true, false, true))
        assertFalse(shouldRunSpeakerTurnDetection(false, true, true, false))
    }
}
