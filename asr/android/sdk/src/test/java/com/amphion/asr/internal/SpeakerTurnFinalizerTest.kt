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
    fun finishSliceDeclaresADepartureTheStreamingRuleMissed() {
        val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        finalizer.accept(squareWave(3_600, 2_000, 2_200))
        finalizer.observeScore(2_000, 0.65f, 0.35f)
        // A trailing window diluted by the owner's own tail never drops twice.
        assertEquals(SpeakerTurnScoreState.BELOW, finalizer.observeScore(3_000, 0.30f, 0.35f))
        assertEquals(false, finalizer.hasPendingDeparture())
        assertNull(finalizer.resolveContainment())

        assertTrue(finalizer.observeFinishSlice(0.10f, 0.35f))
        assertTrue(finalizer.hasPendingDeparture())
        val split = finalizer.resolveContainment()
        assertNotNull(split)
        // The cut predates the whole last target-positive window, as for a streaming containment.
        assertEquals(1_000, split!!.cutSample)
        assertEquals(0.10f, finalizer.lastScore()!!, 0f)
    }

    @Test
    fun finishSliceLeavesAConfirmedTargetAndAnAlreadyDepartedTurnAlone() {
        val target = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        target.accept(squareWave(3_600, 2_000, 2_200))
        target.observeScore(2_000, 0.65f, 0.35f)
        // Still the owner at finish: no departure, and no cut is offered.
        assertEquals(false, target.observeFinishSlice(0.60f, 0.35f))
        assertEquals(false, target.hasPendingDeparture())
        assertNull(target.resolveContainment())

        val departed = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        departed.accept(squareWave(3_600, 2_000, 2_200))
        departed.observeScore(2_000, 0.65f, 0.35f)
        departed.observeScore(3_000, 0.20f, 0.35f)
        departed.observeScore(3_200, 0.10f, 0.35f)
        // The streaming rule already resolved this turn; the finish slice must not re-declare it.
        assertEquals(false, departed.observeFinishSlice(0.10f, 0.35f))

        val unconfirmed = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        unconfirmed.accept(squareWave(3_600, 2_000, 2_200))
        // The owner was never confirmed, so there is no target prefix to protect.
        assertEquals(false, unconfirmed.observeFinishSlice(0.10f, 0.35f))
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

    @Test
    fun silentLowWindowsAfterTheTargetAreNotADeparture() {
        // 鸿蒙 #98 真机：机主停口后两个尾部静音窗口打 0.327 / -0.072，凑够 consecutiveBelow 却没有人接话。
        val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        finalizer.accept(squareWave(3_600, 2_000, 2_200))
        assertEquals(SpeakerTurnScoreState.TARGET_CONFIRMED, finalizer.observeScore(2_000, 0.65f, 0.35f, true))
        assertEquals(SpeakerTurnScoreState.BELOW, finalizer.observeScore(3_000, 0.327f, 0.35f, false))
        assertEquals(SpeakerTurnScoreState.DEPARTURE, finalizer.observeScore(3_200, -0.072f, 0.35f, false))
        assertEquals(2, finalizer.consecutiveLowScores())
        assertEquals(false, finalizer.hasSpeechBearingLowScore())
        assertEquals(false, finalizer.hasPendingDeparture())
    }

    @Test
    fun oneSpeechBearingLowWindowIsEnoughDepartureEvidence() {
        val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        finalizer.accept(squareWave(3_600, 2_000, 2_200))
        finalizer.observeScore(2_000, 0.65f, 0.35f, true)
        assertEquals(SpeakerTurnScoreState.BELOW, finalizer.observeScore(3_000, 0.20f, 0.35f, true))
        // 第二跳落在静音里：接话的人停顿了，离场证据仍然成立。
        assertEquals(SpeakerTurnScoreState.DEPARTURE, finalizer.observeScore(3_200, 0.10f, 0.35f, false))
        assertTrue(finalizer.hasSpeechBearingLowScore())
        assertTrue(finalizer.hasPendingDeparture())
        assertNotNull(finalizer.resolve(listOf(0.3f, 1.0f, 2.2f), 0.35f, leftTargetRightOther))
    }

    @Test
    fun targetReturnClearsSpeechBearingLowScore() {
        val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        finalizer.accept(squareWave(3_600, 2_000, 2_200))
        finalizer.observeScore(2_000, 0.65f, 0.35f, true)
        finalizer.observeScore(2_400, 0.20f, 0.35f, true)
        assertEquals(SpeakerTurnScoreState.TARGET_ACTIVE, finalizer.observeScore(2_600, 0.70f, 0.35f, true))
        assertEquals(false, finalizer.hasSpeechBearingLowScore())
        finalizer.observeScore(3_000, 0.30f, 0.35f, false)
        assertEquals(SpeakerTurnScoreState.DEPARTURE, finalizer.observeScore(3_200, 0.10f, 0.35f, false))
        assertEquals(false, finalizer.hasPendingDeparture())
    }

    @Test
    fun finishDepartureCandidateNeedsASpeechBearingLowWindow() {
        val silent = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        silent.accept(squareWave(3_600, 2_000, 2_200))
        silent.observeScore(2_000, 0.65f, 0.35f, true)
        silent.observeScore(3_000, 0.20f, 0.35f, false)
        assertEquals(false, silent.hasPendingFinishDeparture())

        val spoken = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        spoken.accept(squareWave(3_600, 2_000, 2_200))
        spoken.observeScore(2_000, 0.65f, 0.35f, true)
        spoken.observeScore(3_000, 0.20f, 0.35f, true)
        assertTrue(spoken.hasPendingFinishDeparture())
    }

    @Test
    fun preTargetStateIsReportedRegardlessOfSpeechSoTheCallerCanGateIt() {
        // 静音里的 pre-target 由 SessionImpl 按 speechWasActive 决定是否强制端点；状态机只负责报告。
        val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        finalizer.accept(squareWave(3_600, 2_000, 2_200))
        assertEquals(SpeakerTurnScoreState.WAITING_TARGET, finalizer.observeScore(1_200, 0.07f, 0.35f, false))
        assertEquals(SpeakerTurnScoreState.PRE_TARGET, finalizer.observeScore(1_400, 0.07f, 0.35f, false))
        assertTrue(finalizer.shouldRejectCurrent())
    }

    @Test
    fun unconfirmedUtteranceMustClearTheMeasuredFloor() {
        // 真机上那段 1.6 s 的非机主句子打 0.362，越过默认阈值 0.35 被当作机主发布。
        assertEquals(0.45f, speakerFinalGateScore(0.35f, false))
        assertTrue(0.362f < speakerFinalGateScore(0.35f, false))
        // 机主自己的短句最低实测 0.525，仍在门上。
        assertTrue(0.525f >= speakerFinalGateScore(0.35f, false))
    }

    @Test
    fun confirmedUtteranceKeepsTheCallerThreshold() {
        assertEquals(0.35f, speakerFinalGateScore(0.35f, true))
        assertTrue(0.362f >= speakerFinalGateScore(0.35f, true))
    }

    @Test
    fun aStricterCallerThresholdWins() {
        assertEquals(0.60f, speakerFinalGateScore(0.60f, false))
        assertEquals(0.60f, speakerFinalGateScore(0.60f, true))
        assertEquals(0.60f, speakerFinishSliceGateScore(0.60f))
    }

    @Test
    fun finishSliceUsesTheMeasuredFloorEvenAfterConfirmation() {
        // 真机 turn-05：收尾那 1.2 s 切片打 0.445，高于默认阈值 0.35，离场没被认定。
        assertEquals(0.45f, speakerFinishSliceGateScore(0.35f))
        val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        finalizer.accept(squareWave(3_600, 2_000, 2_200))
        finalizer.observeScore(2_000, 0.65f, 0.35f)
        assertEquals(false, finalizer.observeFinishSlice(0.445f, 0.35f))
        assertTrue(finalizer.observeFinishSlice(0.445f, speakerFinishSliceGateScore(0.35f)))
        assertTrue(finalizer.hasPendingDeparture())
    }

    @Test
    fun aPendingDepartureStillHasASafePrefixToContain() {
        // 真机 turn-02/03/04：流式确认了离场，声学解析器等上下文而音频到此为止。
        val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        finalizer.accept(squareWave(3_600, 2_000, 2_200))
        finalizer.observeScore(2_000, 0.65f, 0.35f)
        finalizer.observeScore(3_000, 0.20f, 0.35f)
        assertEquals(SpeakerTurnScoreState.DEPARTURE, finalizer.observeScore(3_200, 0.10f, 0.35f))
        assertTrue(finalizer.hasPendingDeparture())
        val contained = finalizer.resolveContainment()
        assertNotNull(contained)
        // 切点就是保守前缀的末尾：最后一次确认还是机主的位置，不猜边界
        assertEquals(finalizer.safePrefixEndSample(), contained!!.cutSample)
        assertTrue(contained.cutSample > 0)
        assertTrue(contained.suffix.isNotEmpty())
    }

    // ---- 到达侧切分（缺陷 #102）：非机主先说、机主接上并成一句 ----

    /** 1 kHz 采样、1 s 窗 / 0.2 s 跳：前 1.4 s 为非机主语音，之后机主语音。 */
    private fun arrivalWave(total: Int = 3_000, otherEnd: Int = 1_400): FloatArray =
        FloatArray(total) { i -> if (i < otherEnd) (if (i % 2 == 0) 0.15f else -0.15f) else (if (i % 2 == 0) 0.2f else -0.2f) }

    @Test
    fun arrivalAfterSpeechBearingLowHopsCutsAtTheConfirmingWindowStart() {
        val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        finalizer.accept(arrivalWave())
        assertEquals(SpeakerTurnScoreState.WAITING_TARGET, finalizer.observeScore(1_000, 0.24f, 0.35f, speechWasActive = true))
        assertEquals(SpeakerTurnScoreState.PRE_TARGET, finalizer.observeScore(1_200, 0.30f, 0.35f, speechWasActive = true))
        // 2 000 处窗口（1 000–2 000）里机主已经占多数：确认目标。
        assertEquals(SpeakerTurnScoreState.TARGET_CONFIRMED, finalizer.observeScore(2_000, 0.48f, 0.35f, speechWasActive = true))
        val split = finalizer.resolveArrival(minimumPrefixSpeechSamples = 800)
        assertNotNull(split)
        split!!
        assertEquals(1_000, split.cutSample)
        assertEquals(false, split.prefixIsTarget)
        assertEquals(1_000, split.prefix.size)
        assertEquals(2_000, split.suffix.size)
        assertTrue(finalizer.lastResolutionReason().startsWith("arrival-safe-prefix:window-start:1000"))
    }

    @Test
    fun arrivalSnapsTheCutToTheQuietValleyBetweenTheTwoSpeakers() {
        // 非机主 0–1 200，停顿 1 200–1 500，机主 1 500 起；确认窗口（1 500–2 500）起点正好落在停顿里。
        val wave = FloatArray(3_500) { i ->
            when {
                i < 1_200 -> if (i % 2 == 0) 0.15f else -0.15f
                i < 1_500 -> 0f
                else -> if (i % 2 == 0) 0.2f else -0.2f
            }
        }
        val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        finalizer.accept(wave)
        assertEquals(SpeakerTurnScoreState.WAITING_TARGET, finalizer.observeScore(1_400, 0.24f, 0.35f, speechWasActive = true))
        assertEquals(SpeakerTurnScoreState.TARGET_CONFIRMED, finalizer.observeScore(2_500, 0.52f, 0.35f, speechWasActive = true))
        // 对齐到静音谷后前缀只需 0.3 s 语音；前缀 1.2 s 非机主语音全部切走，后缀从机主开口处开始。
        val split = finalizer.resolveArrival(minimumPrefixSpeechSamples = 300, minimumUnalignedPrefixSpeechSamples = 1_000)
        assertNotNull(split)
        split!!
        assertEquals(1_500, split.cutSample)
        assertEquals(false, split.prefixIsTarget)
        assertEquals(0.2f, split.suffix[0], 0f)
        assertTrue(finalizer.lastResolutionReason().startsWith("arrival-safe-prefix:valley:1500"))
    }

    @Test
    fun arrivalIsNotSplitWhenThePrefixIsMostlySilenceOrNoLowSpeechHopPrecededTheTarget() {
        // 机主慢起头：确认之前只有一跳低分，且前缀 1 s 里只有 0.3 s 语音 → 不切。
        val slowStart = FloatArray(3_000) { i -> if (i in 700 until 3_000) (if (i % 2 == 0) 0.2f else -0.2f) else 0f }
        val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        finalizer.accept(slowStart)
        assertEquals(SpeakerTurnScoreState.WAITING_TARGET, finalizer.observeScore(1_000, 0.30f, 0.35f, speechWasActive = true))
        assertEquals(SpeakerTurnScoreState.TARGET_CONFIRMED, finalizer.observeScore(2_000, 0.60f, 0.35f, speechWasActive = true))
        assertNull(finalizer.resolveArrival(minimumPrefixSpeechSamples = 800))
        assertTrue(finalizer.lastResolutionReason().startsWith("arrival-prefix-speech-too-short:"))

        // 静音里的低分窗口（speechWasActive=false）不构成到达证据。
        val silentThenTarget = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        silentThenTarget.accept(arrivalWave())
        assertEquals(SpeakerTurnScoreState.WAITING_TARGET, silentThenTarget.observeScore(1_000, 0.07f, 0.35f, speechWasActive = false))
        assertEquals(SpeakerTurnScoreState.TARGET_CONFIRMED, silentThenTarget.observeScore(2_000, 0.60f, 0.35f, speechWasActive = true))
        assertNull(silentThenTarget.resolveArrival(minimumPrefixSpeechSamples = 800))
        assertEquals("arrival-not-ready", silentThenTarget.lastResolutionReason())

        // 没确认目标就没有到达。
        val waiting = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        waiting.accept(arrivalWave())
        waiting.observeScore(1_000, 0.2f, 0.35f, speechWasActive = true)
        assertNull(waiting.resolveArrival(minimumPrefixSpeechSamples = 800))
    }

    @Test
    fun arrivalPrefersTheLastLongEnoughValleyOverAnEarlierLongerPause() {
        // 非机主 0–600，句内停顿 600–1 000（0.4 s），非机主 1 000–1 700，交接停顿 1 700–2 000（0.3 s），机主 2 000 起。
        val wave = FloatArray(4_000) { i ->
            when {
                i < 600 || (i in 1_000 until 1_700) -> if (i % 2 == 0) 0.15f else -0.15f
                i < 2_000 -> 0f
                else -> if (i % 2 == 0) 0.2f else -0.2f
            }
        }
        val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        finalizer.accept(wave)
        assertEquals(SpeakerTurnScoreState.WAITING_TARGET, finalizer.observeScore(1_800, 0.24f, 0.35f, speechWasActive = true))
        // 确认窗口 1 600–2 600：里面有交接停顿 1 700–2 000，之前（搜索范围从 1 400 起）没有更长的停顿可选。
        assertEquals(SpeakerTurnScoreState.TARGET_CONFIRMED, finalizer.observeScore(2_600, 0.52f, 0.35f, speechWasActive = true))
        val split = finalizer.resolveArrival(300, 1_000)
        assertNotNull(split)
        assertEquals(2_000, split!!.cutSample)
        assertEquals(0.2f, split.suffix[0], 0f)
    }

    @Test
    fun arrivalEvidenceIsClearedByResetAndDoesNotLeakIntoDepartureLogic() {
        val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        finalizer.accept(arrivalWave())
        finalizer.observeScore(1_000, 0.24f, 0.35f, speechWasActive = true)
        finalizer.observeScore(2_000, 0.48f, 0.35f, speechWasActive = true)
        assertNotNull(finalizer.resolveArrival(800))
        // 到达切分不等于离场：没有 departure，也不会给出 containment。
        assertEquals(false, finalizer.hasPendingDeparture())
        assertNull(finalizer.resolveContainment())
        finalizer.reset()
        finalizer.accept(arrivalWave())
        assertEquals(SpeakerTurnScoreState.TARGET_CONFIRMED, finalizer.observeScore(1_000, 0.6f, 0.35f))
        assertNull(finalizer.resolveArrival(800))
        assertEquals("arrival-not-ready", finalizer.lastResolutionReason())
    }
}
