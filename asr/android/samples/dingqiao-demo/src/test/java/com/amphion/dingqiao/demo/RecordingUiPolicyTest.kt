package com.amphion.dingqiao.demo

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RecordingUiPolicyTest {

    @Test
    fun elapsedLabelMakesActiveRecordingDurationObvious() {
        assertEquals("00:00.0", RecordingUiPolicy.elapsedLabel(0))
        assertEquals("00:03.4", RecordingUiPolicy.elapsedLabel(3_456))
        assertEquals("01:02.9", RecordingUiPolicy.elapsedLabel(62_999))
    }

    @Test
    fun registrationRemainsLockedWhileRecordingOrRegistering() {
        assertFalse(RecordingUiPolicy.canRegister(sampleCount = 1, recording = true, registering = false))
        assertFalse(RecordingUiPolicy.canRegister(sampleCount = 1, recording = false, registering = true))
        assertFalse(RecordingUiPolicy.canRegister(sampleCount = 0, recording = false, registering = false))
        assertTrue(RecordingUiPolicy.canRegister(sampleCount = 1, recording = false, registering = false))
    }

    @Test
    fun durationGuidanceMatchesThreeToEightSecondContract() {
        assertEquals(RecordingUiPolicy.DurationState.TOO_SHORT, RecordingUiPolicy.durationState(2_999))
        assertEquals(RecordingUiPolicy.DurationState.READY, RecordingUiPolicy.durationState(3_000))
        assertEquals(RecordingUiPolicy.DurationState.READY, RecordingUiPolicy.durationState(8_000))
        assertEquals(RecordingUiPolicy.DurationState.TOO_LONG, RecordingUiPolicy.durationState(8_001))
    }
}
