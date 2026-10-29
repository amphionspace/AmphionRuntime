package com.amphion.asr.internal

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Ported from asr/tools/tests/test_harmony_speaker_turn_finalizer.py so both platforms split alike. */
class SpeakerTurnFinalizerTest {
    private fun squareWave(total: Int, firstEnd: Int, secondStart: Int): FloatArray {
        val samples = FloatArray(total)
        for (i in 0 until firstEnd) samples[i] = if (i % 2 == 0) 0.2f else -0.2f
        for (i in secondStart until total) samples[i] = if (i % 2 == 0) 0.15f else -0.15f
        return samples
    }

    private val leftTargetRightOther: SpeakerRangeScorer = { _, start, end ->
        when {
            end <= 2_200 -> 0.60f
            start >= 2_200 -> 0.10f
            else -> null
        }
    }

    @Test
    fun sequentialTurnUsesQuietValleyAndReplaysSuffix() {
        val samples = squareWave(3_600, 2_000, 2_200)
        val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        finalizer.accept(samples)
        assertEquals(SpeakerTurnScoreState.TARGET_CONFIRMED, finalizer.observeScore(2_000, 0.65f, 0.35f))
        assertEquals(SpeakerTurnScoreState.BELOW, finalizer.observeScore(3_000, 0.20f, 0.35f))
        assertEquals(SpeakerTurnScoreState.DEPARTURE, finalizer.observeScore(3_200, 0.10f, 0.35f))

        val split = finalizer.resolve(listOf(0.3f, 1.0f, 2.2f), 0.35f, leftTargetRightOther)
        assertNotNull(split)
        split!!
        assertEquals(2_200, split.cutSample)
        assertEquals(2_200, split.prefix.size)
        assertEquals(1_400, split.suffix.size)
        assertEquals(samples[2_200], split.suffix[0], 0f)
        assertTrue(finalizer.lastResolutionReason().startsWith("split:candidate=2200"))
    }

    @Test
    fun splitPreservesAlignedRawAndAgcDomains() {
        val raw = squareWave(3_600, 2_000, 2_200)
        val processed = FloatArray(raw.size) { raw[it] * 2f }
        val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        finalizer.accept(raw, processed)
        finalizer.observeScore(2_000, 0.65f, 0.35f)
        finalizer.observeScore(3_000, 0.20f, 0.35f)
        finalizer.observeScore(3_200, 0.10f, 0.35f)
        val split = finalizer.resolve(listOf(0.3f, 1.0f, 2.2f), 0.35f, leftTargetRightOther)
        assertNotNull(split)
        split!!
        assertEquals(split.prefix.size, split.processedPrefix.size)
        assertEquals(split.suffix.size, split.processedSuffix.size)
        assertEquals(split.prefix[100] * 2f, split.processedPrefix[100], 0f)
        assertEquals(split.suffix[100] * 2f, split.processedSuffix[100], 0f)
    }

    @Test
    fun finishRejectsReplayedSuffixWithoutAConfirmedTarget() {
        assertEquals(true, shouldRejectSpeakerVadFinal(true, true, false, null))
        assertEquals(true, shouldRejectSpeakerVadFinal(true, false, false, null))
        assertEquals(false, shouldRejectSpeakerVadFinal(true, false, true, null))
        assertEquals(false, shouldRejectSpeakerVadFinal(false, true, false, null))
    }

    @Test
    fun ambiguousBoundariesDoNotClaimAPreciseSplit() {
        val samples = squareWave(3_600, 2_000, 2_200)
        val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        finalizer.accept(samples)
        finalizer.observeScore(2_000, 0.65f, 0.35f)
        finalizer.observeScore(3_000, 0.20f, 0.35f)
        finalizer.observeScore(3_200, 0.10f, 0.35f)
        // Both sides still look like the target: no verified boundary, no split.
        val split = finalizer.resolve(listOf(0.3f, 1.0f, 2.2f), 0.35f, { _, _, _ -> 0.5f })
        assertNull(split)
        assertTrue(finalizer.lastResolutionReason().startsWith("no-verified-boundary:"))
    }

    @Test
    fun strongHintWaitsForItsRightContextInsteadOfTruncating() {
        val samples = squareWave(3_000, 2_000, 2_200)
        val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        finalizer.accept(samples)
        finalizer.observeScore(2_000, 0.65f, 0.35f)
        finalizer.observeScore(2_600, 0.20f, 0.35f)
        finalizer.observeScore(2_800, 0.10f, 0.35f)
        // The token at 2.2 s has less than one window of audio after it; wait rather than guess.
        val split = finalizer.resolve(listOf(2.2f), 0.35f, leftTargetRightOther)
        assertNull(split)
        assertEquals("insufficient-refine-context", finalizer.lastResolutionReason())
        assertTrue(finalizer.needsMoreContext())
    }

    @Test
    fun containmentRequiresAConfirmedUncappedDeparture() {
        val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        finalizer.accept(squareWave(3_600, 2_000, 2_200))
        finalizer.observeScore(2_000, 0.65f, 0.35f)
        finalizer.observeScore(3_000, 0.20f, 0.35f)
        assertNull(finalizer.resolveContainment())
        assertEquals("containment-not-ready", finalizer.lastResolutionReason())
        finalizer.observeScore(3_200, 0.10f, 0.35f)
        val split = finalizer.resolveContainment()
        assertNotNull(split)
        // The cut predates the whole last target-positive window (end 2000 - window 1000).
        assertEquals(1_000, split!!.cutSample)
        assertEquals("containment-safe-prefix:1000", finalizer.lastResolutionReason())

        val capped = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 3_000)
        capped.accept(squareWave(3_600, 2_000, 2_200))
        capped.observeScore(2_000, 0.65f, 0.35f)
        capped.observeScore(3_000, 0.20f, 0.35f)
        capped.observeScore(3_200, 0.10f, 0.35f)
        assertNull(capped.resolveContainment())
        assertEquals("containment-buffer-capped", capped.lastResolutionReason())
    }

    @Test
    fun preTargetLowScoresRejectTheUtteranceAndResetClearsEverything() {
        val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        finalizer.accept(FloatArray(2_000) { 0.1f })
        assertEquals(SpeakerTurnScoreState.WAITING_TARGET, finalizer.observeScore(1_000, 0.1f, 0.35f))
        assertEquals(SpeakerTurnScoreState.PRE_TARGET, finalizer.observeScore(1_200, 0.1f, 0.35f))
        assertTrue(finalizer.shouldRejectCurrent())
        assertEquals(2_000, finalizer.sampleCount())
        finalizer.reset()
        assertEquals(0, finalizer.sampleCount())
        assertEquals(false, finalizer.shouldRejectCurrent())
        assertEquals(false, finalizer.isTargetConfirmed())
        assertNull(finalizer.lastScore())
    }

    @Test
    fun targetReturnClearsADepartureInProgress() {
        val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        finalizer.accept(squareWave(3_600, 2_000, 2_200))
        finalizer.observeScore(2_000, 0.65f, 0.35f)
        assertEquals(SpeakerTurnScoreState.BELOW, finalizer.observeScore(3_000, 0.20f, 0.35f))
        assertEquals(SpeakerTurnScoreState.TARGET_ACTIVE, finalizer.observeScore(3_200, 0.70f, 0.35f))
        assertEquals(0, finalizer.consecutiveLowScores())
        assertEquals(false, finalizer.hasPendingDeparture())
        assertEquals(2_200, finalizer.safePrefixEndSample())
    }
}
