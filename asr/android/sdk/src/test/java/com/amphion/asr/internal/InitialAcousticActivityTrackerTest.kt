package com.amphion.asr.internal

import com.amphion.asr.SessionConfig
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class InitialAcousticActivityTrackerTest {
    @Test
    fun sustainedSignalBecomesRecentAfterSixtyMilliseconds() {
        val tracker = InitialAcousticActivityTracker(sampleRate = 16_000)
        val frame = FloatArray(320) { 0.02f }

        tracker.observe(frame)
        tracker.observe(frame)
        assertFalse(tracker.hasRecentActivity())
        tracker.observe(frame)
        assertTrue(tracker.hasRecentActivity())
    }

    @Test
    fun resultDoesNotDependOnCallerChunking() {
        val framed = InitialAcousticActivityTracker(sampleRate = 16_000)
        val merged = InitialAcousticActivityTracker(sampleRate = 16_000)
        val signal = FloatArray(960) { 0.02f }

        signal.asList().chunked(137).forEach { framed.observe(it.toFloatArray()) }
        merged.observe(signal)

        assertTrue(framed.hasRecentActivity())
        assertTrue(merged.hasRecentActivity())
    }

    @Test
    fun silenceBreaksConsecutiveActivityAndOldActivityExpires() {
        val tracker = InitialAcousticActivityTracker(sampleRate = 16_000)
        val signal = FloatArray(320) { 0.02f }

        tracker.observe(signal)
        tracker.observe(signal)
        tracker.observe(FloatArray(320))
        tracker.observe(signal)
        assertFalse(tracker.hasRecentActivity())

        tracker.observe(signal)
        tracker.observe(signal)
        assertTrue(tracker.hasRecentActivity())
        tracker.observe(FloatArray(16_000))
        assertFalse(tracker.hasRecentActivity())
    }

    @Test
    fun lowLevelNoiseDoesNotBecomeActivity() {
        val tracker = InitialAcousticActivityTracker(sampleRate = 16_000)
        tracker.observe(FloatArray(3_200) { 0.005f })

        assertFalse(tracker.hasRecentActivity())
    }

    @Test
    fun varyingSpeechLikeSignalIsDistinguishedFromSteadyTone() {
        val speechLike = InitialAcousticActivityTracker(sampleRate = 16_000)
        val steadyTone = InitialAcousticActivityTracker(sampleRate = 16_000)
        val levels = floatArrayOf(0.02f, 0.08f, 0.03f, 0.12f)

        for (level in levels) {
            speechLike.observe(FloatArray(320) { index -> if (index % 20 < 10) level else -level })
            steadyTone.observe(FloatArray(320) { index -> if (index % 2 == 0) 0.02f else -0.02f })
        }

        assertTrue(speechLike.hasSpeechLikeActivity())
        assertTrue(speechLike.hasRecentSpeechLikeActivity())
        assertFalse(steadyTone.hasSpeechLikeActivity())
        speechLike.observe(FloatArray(16_000))
        assertFalse(speechLike.hasRecentActivity())
        assertTrue(speechLike.hasSpeechLikeActivity())
        assertFalse(speechLike.hasRecentSpeechLikeActivity())
    }

    @Test
    fun separatedVaryingPulsesDoNotBecomeSpeechLikeActivity() {
        val tracker = InitialAcousticActivityTracker(sampleRate = 16_000)

        for (level in floatArrayOf(0.02f, 0.08f, 0.03f)) {
            tracker.observe(FloatArray(320) { index -> if (index % 20 < 10) level else -level })
            tracker.observe(FloatArray(320))
        }

        assertFalse(tracker.hasRecentActivity())
        assertFalse(tracker.hasSpeechLikeActivity())
        assertFalse(tracker.hasRecentSpeechLikeActivity())
    }

    @Test
    fun oneNewPulseDoesNotRefreshOldSpeechLikeActivity() {
        val tracker = InitialAcousticActivityTracker(sampleRate = 16_000)
        for (level in floatArrayOf(0.02f, 0.08f, 0.03f, 0.12f)) {
            tracker.observe(FloatArray(320) { index -> if (index % 20 < 10) level else -level })
        }
        tracker.observe(FloatArray(16_000))
        tracker.observe(FloatArray(320) { index -> if (index % 20 < 10) 0.08f else -0.08f })

        assertTrue(tracker.hasSpeechLikeActivity())
        assertFalse(tracker.hasRecentSpeechLikeActivity())
    }
}

class SessionConfigTest {
    @Test
    fun confirmationGraceRejectsNegativeValues() {
        assertTrue(runCatching { SessionConfig(initialSilenceConfirmationGraceMs = -1) }.isFailure)
        assertTrue(runCatching { SessionConfig(initialSilenceConfirmationGraceMs = 0) }.isSuccess)
    }
}
