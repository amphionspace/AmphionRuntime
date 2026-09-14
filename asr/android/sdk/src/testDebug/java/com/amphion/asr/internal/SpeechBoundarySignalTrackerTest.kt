package com.amphion.asr.internal

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SpeechBoundarySignalTrackerTest {
    @Test
    fun vadSpeechAndAsrEvidenceAnnounceOnlyOneBeginUntilEndpoint() {
        val tracker = SpeechBoundarySignalTracker()
        assertTrue(tracker.observeSpeech())
        assertFalse(tracker.observeSpeech())
        tracker.endpoint()
        assertTrue(tracker.observeSpeech())
    }

    @Test
    fun asrEvidenceCanOpenAnUtteranceWhenVadMissesOnset() {
        val tracker = SpeechBoundarySignalTracker()
        assertFalse(tracker.observeSpeech(hasEvidence = false))
        assertTrue(tracker.observeSpeech(hasEvidence = true))
        tracker.endpoint()
        assertTrue(tracker.observeSpeech(hasEvidence = true))
    }

    @Test
    fun pureSilenceNeverAnnouncesSpeech() {
        val tracker = SpeechBoundarySignalTracker()
        repeat(50) { assertFalse(tracker.observeSpeech(hasEvidence = false)) }
        tracker.endpoint()
        assertFalse(tracker.observeSpeech(hasEvidence = false))
    }
}
