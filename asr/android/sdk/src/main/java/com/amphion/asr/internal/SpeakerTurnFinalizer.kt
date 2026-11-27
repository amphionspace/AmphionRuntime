package com.amphion.asr.internal

import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sqrt

/**
 * 流式机器从未确认过目标说话人的句子，句级分还要过这条实测下沿。
 *
 * 依据 `asr/tools/speaker/18_eval_short_segment_threshold.py`：同一注册下机主短句最低
 * 0.525 / 0.600 / 0.603 / 0.636（1.0~3.0 s），非机主最高 0.400 / 0.377 / 0.432 / 0.459，
 * 0.35 到 0.52 之间是一条空带。鸿蒙真机上一段 1.6 s 的非机主句子打到 0.362，越过默认阈值
 * 0.35 被当作机主发布；该句太短，流式判定（winSec + hopSec）来不及出结论，只剩句级分可依。
 *
 * 与 Harmony 的 `UNCONFIRMED_SPEAKER_FINAL_MIN_SCORE` 同值。注册音与测试音同一会话时机主一侧
 * 偏乐观，跨会话注册需用客户真实声纹复测后才能认为该下沿在生产上成立。
 */
internal const val UNCONFIRMED_SPEAKER_FINAL_MIN_SCORE = 0.45f

/** 到达侧切分认可的最短交接停顿；机主句内停顿一般短于它，换人停顿一般长于它（缺陷 #102 实测 0.48 s）。 */
internal const val ARRIVAL_VALLEY_MIN_SEC = 0.25f

/** 句级门：已确认目标用调用方阈值；未确认时取调用方阈值与实测下沿的较大者（调用方更严时以其为准）。 */
internal fun speakerFinalGateScore(threshold: Float, targetConfirmed: Boolean): Float =
    if (targetConfirmed) threshold else max(threshold, UNCONFIRMED_SPEAKER_FINAL_MIN_SCORE)

/**
 * 收尾切片门：切片只有一两秒，落在实测空带那一段，所以一律按实测下沿判离场。
 *
 * 判错（把机主自己的尾巴当成换人）的代价是机主尾部被保守切点截掉几个字；判漏的代价是把别人的话
 * 录成机主的。实测机主短句最低 0.525，离这条线还有余量。
 */
internal fun speakerFinishSliceGateScore(threshold: Float): Float =
    max(threshold, UNCONFIRMED_SPEAKER_FINAL_MIN_SCORE)

/**
 * Speaker VAD score state after one trailing-window score. Mirrors the Harmony
 * `SpeakerTurnFinalizer.ts` contract so both platforms gate target -> other turns the same way.
 */
internal enum class SpeakerTurnScoreState {
    WAITING_TARGET,
    TARGET_CONFIRMED,
    TARGET_ACTIVE,
    BELOW,
    PRE_TARGET,
    DEPARTURE,
}

/** Scores a PCM range against the enrolled target; returns null when no embedding is possible. */
internal typealias SpeakerRangeScorer = (samples: FloatArray, startSample: Int, endSample: Int) -> Float?

internal class SpeakerTurnSplit(
    val cutSample: Int,
    val prefix: FloatArray,
    val suffix: FloatArray,
    processedPrefix: FloatArray? = null,
    processedSuffix: FloatArray? = null,
    /** 离场切分前缀是机主（发布）；到达切分前缀是非机主（拒绝），后缀才是机主。 */
    val prefixIsTarget: Boolean = true,
) {
    val processedPrefix: FloatArray = processedPrefix ?: prefix
    val processedSuffix: FloatArray = processedSuffix ?: suffix
}

/**
 * Owns the bounded PCM and score ledger needed to commit a clean target -> other boundary.
 *
 * A split is returned only after consecutive low speaker scores, a deterministic acoustic/token
 * candidate, and independent target-left/non-target-right verification. For a confirmed sequential
 * departure the caller may fall back to the conservative prefix from [resolveContainment]; overlap
 * remains explicitly outside this module's contract. Port of the Harmony finalizer; the
 * diarization-assisted resolvers are not ported yet because Android has no speaker-turn segmenter
 * binding, so Android follows Harmony's "segmenter unavailable" path.
 */
internal class SpeakerTurnFinalizer(
    sampleRate: Int,
    windowSamples: Int,
    hopSamples: Int,
    consecutiveBelow: Int,
    maximumSamples: Int,
) {
    private val sampleRate = max(1, sampleRate)
    private val windowSamples = max(1, windowSamples)
    private val hopSamples = max(1, hopSamples)
    private val consecutiveBelow = max(1, consecutiveBelow)
    private val maximumSamples = max(1, maximumSamples)
    private val parts = mutableListOf<FloatArray>()
    private val processedParts = mutableListOf<FloatArray>()
    private var retainedSamples = 0
    private var capped = false
    private var targetSeen = false
    private var belowCount = 0
    private var lastTargetEndSample = -1
    private var firstBelowEndSample = -1
    private var lastObservedEndSample = -1
    private var departureSeen = false
    private var speechBearingLowScore = false
    private var rejectBeforeTarget = false
    private var latestScore: Float? = null
    private var lastTargetScore: Float? = null
    private var resolutionReason = "not-resolved"
    private var pendingCandidatePrefixEndSample = -1
    // 到达侧（非机主 → 机主）证据：目标确认之前带语音的低分窗口数，以及确认窗口的起点。
    private var preTargetSpeechLowHops = 0
    private var arrivalWindowStartSample = -1

    fun accept(samples: FloatArray, processedSamples: FloatArray = samples) {
        if (samples.isEmpty()) return
        require(processedSamples.size == samples.size) {
            "raw and processed speaker-turn samples must have the same length"
        }
        val available = maximumSamples - retainedSamples
        if (samples.size > available) capped = true
        val retained = min(samples.size, max(0, available))
        if (retained > 0) {
            parts += samples.copyOfRange(0, retained)
            processedParts += processedSamples.copyOfRange(0, retained)
            retainedSamples += retained
        }
    }

    /**
     * `speechWasActive` 是这一跳窗口有没有 VAD 确认的语音（与鸿蒙 `SpeakerTurnFinalizer.observeScore` 同义）。
     *
     * 窗口是固定 winSec 的尾部音频，机主停口后它会被静音逐步稀释，嵌入随之失真：同一段机主语音，
     * 窗口满时打 0.545，尾部 0.93 s 静音时打 -0.072（鸿蒙 #98 真机实测）。把这种分数当成"机主离场"，
     * 就会在机主自己的句子里凑出 departure 并切一刀，把句尾切掉。分数照常记录和上报；只有"离场"
     * 这个结论要求至少一跳低分窗口带真实语音。判据是有无语音，不是语音时长占比，短插话仍然算证据。
     */
    fun observeScore(
        endSample: Int,
        score: Float,
        threshold: Float,
        speechWasActive: Boolean = true,
    ): SpeakerTurnScoreState {
        val end = max(0, endSample)
        lastObservedEndSample = end
        latestScore = score
        if (score >= threshold) {
            val firstTarget = !targetSeen
            if (firstTarget) arrivalWindowStartSample = max(0, end - windowSamples)
            targetSeen = true
            belowCount = 0
            lastTargetEndSample = end
            lastTargetScore = score
            firstBelowEndSample = -1
            departureSeen = false
            speechBearingLowScore = false
            rejectBeforeTarget = false
            return if (firstTarget) SpeakerTurnScoreState.TARGET_CONFIRMED else SpeakerTurnScoreState.TARGET_ACTIVE
        }
        if (speechWasActive) speechBearingLowScore = true
        belowCount += 1
        if (!targetSeen) {
            if (speechWasActive) preTargetSpeechLowHops += 1
            if (belowCount >= consecutiveBelow) {
                rejectBeforeTarget = true
                return SpeakerTurnScoreState.PRE_TARGET
            }
            return SpeakerTurnScoreState.WAITING_TARGET
        }
        if (belowCount == 1) firstBelowEndSample = end
        if (belowCount >= consecutiveBelow) {
            departureSeen = true
            return SpeakerTurnScoreState.DEPARTURE
        }
        return SpeakerTurnScoreState.BELOW
    }

    fun isTargetConfirmed(): Boolean = targetSeen
    fun shouldRejectCurrent(): Boolean = rejectBeforeTarget
    fun lastScore(): Float? = latestScore
    fun consecutiveLowScores(): Int = belowCount
    fun sampleCount(): Int = retainedSamples
    fun samples(): FloatArray = concat(parts, retainedSamples)
    fun processedSamples(): FloatArray = concat(processedParts, retainedSamples)
    fun hopSamples(): Int = hopSamples

    /** The latest PCM position that predates the last target-positive window entirely. */
    fun safePrefixEndSample(): Int =
        if (lastTargetEndSample < 0) 0 else max(0, lastTargetEndSample - windowSamples)

    fun candidatePrefixEndSample(): Int = pendingCandidatePrefixEndSample
    fun lastResolutionReason(): String = resolutionReason
    fun deferResolution(reason: String) {
        resolutionReason = reason
    }

    fun needsMoreContext(): Boolean =
        resolutionReason == "insufficient-refine-context" ||
            resolutionReason == "diarizer-loading" ||
            (resolutionReason.startsWith("sequential-boundary-ambiguous:") &&
                resolutionReason.endsWith(":insufficient-refine-context"))

    /** 至少一跳低分窗口带 VAD 语音，离场才有声学依据（见 [observeScore]）。 */
    fun hasSpeechBearingLowScore(): Boolean = speechBearingLowScore
    fun hasPendingDeparture(): Boolean = departureSeen && speechBearingLowScore

    /**
     * 到达侧切分（缺陷 #102）：目标刚被确认，而这句里确认之前已有带语音的低分窗口，说明句首是别人在说、
     * 机主随后接上（停顿短于 vadEnd 时两人并成一句）。
     *
     * 切点优先对齐到确认窗口附近的静音谷（两人交接时通常有几百毫秒停顿）：在 [窗口起点 − 一跳, 窗口终点]
     * 内取最后一个不短于 [ARRIVAL_VALLEY_MIN_SEC] 的静音段，切在静音段末尾，前缀是谷之前的部分——
     * 机主刚开口的一两秒里很少有这么长的停顿，而非机主句内的停顿（实测 0.32 s）会被更靠后的交接停顿
     * （0.48 s）取代。对齐成功时前缀语音至少要有
     * [minimumPrefixSpeechSamples]（调用方取 0.3 s）；找不到静音谷时退回确认窗口起点，并要求前缀语音
     * 至少 [minimumUnalignedPrefixSpeechSamples]（调用方取 1.0 s），避免把机主自己的慢起头切掉。
     * 前缀按非机主拒绝、后缀作为机主重放。只能在目标刚确认、缓冲未截断时调用。
     */
    fun resolveArrival(
        minimumPrefixSpeechSamples: Int,
        minimumUnalignedPrefixSpeechSamples: Int = minimumPrefixSpeechSamples,
    ): SpeakerTurnSplit? {
        resolutionReason = "arrival-not-ready"
        if (!targetSeen || capped || preTargetSpeechLowHops <= 0 || arrivalWindowStartSample < 0) {
            if (capped) resolutionReason = "arrival-buffer-capped"
            return null
        }
        val windowStart = arrivalWindowStartSample
        if (windowStart <= 0 || windowStart >= retainedSamples) {
            resolutionReason = "arrival-no-safe-prefix:$windowStart"
            return null
        }
        val all = samples()
        val frameSamples = max(1, sampleRate / 50)
        val searchStart = max(0, windowStart - hopSamples)
        val searchEnd = min(retainedSamples, windowStart + windowSamples)
        // 静音段从缓冲起点开始统计（交接停顿可能在搜索起点之前就开始），只要求它结束在搜索范围内。
        val valley = lastQuietRun(all, 0, searchEnd, frameSamples, (sampleRate * ARRIVAL_VALLEY_MIN_SEC).roundToInt(), endAfter = searchStart)
        val cutSample: Int
        val speech: Int
        val minimumSpeech: Int
        val how: String
        if (valley != null && valley.second > 0 && valley.second < retainedSamples) {
            cutSample = valley.second
            speech = speechSamplesEstimate(all, 0, valley.first)
            minimumSpeech = minimumPrefixSpeechSamples
            how = "valley"
        } else {
            cutSample = windowStart
            speech = speechSamplesEstimate(all, 0, windowStart)
            minimumSpeech = minimumUnalignedPrefixSpeechSamples
            how = "window-start"
        }
        if (speech < minimumSpeech) {
            resolutionReason = "arrival-prefix-speech-too-short:$how:$speech"
            return null
        }
        val processed = processedSamples()
        resolutionReason = "arrival-safe-prefix:$how:$cutSample:speech=$speech"
        return SpeakerTurnSplit(
            cutSample, all.copyOfRange(0, cutSample), all.copyOfRange(cutSample, all.size),
            processed.copyOfRange(0, cutSample), processed.copyOfRange(cutSample, processed.size),
            prefixIsTarget = false,
        )
    }

    /** 与 [findQuietRun] 同一静音判据，但返回范围内最后一个长度不少于 [minimumRunSamples] 的静音段。 */
    private fun lastQuietRun(
        samples: FloatArray,
        start: Int,
        end: Int,
        frameSamples: Int,
        minimumRunSamples: Int,
        endAfter: Int = start,
    ): Pair<Int, Int>? {
        var referenceRms = 0f
        val frames = mutableListOf<Float>()
        var offset = start
        while (offset + frameSamples <= end) {
            val rms = rangeRms(samples, offset, offset + frameSamples)
            frames += rms
            referenceRms = max(referenceRms, rms)
            offset += frameSamples
        }
        if (frames.isEmpty() || referenceRms <= 0f) return null
        val quietThreshold = min(0.01f, referenceRms * 0.15f)
        val minimumQuietFrames = max(1, ceil(minimumRunSamples.toDouble() / frameSamples).toInt())
        var runStart = -1
        var last: Pair<Int, Int>? = null
        for (index in 0..frames.size) {
            val quiet = index < frames.size && frames[index] <= quietThreshold
            if (quiet && runStart < 0) runStart = index
            if (quiet) continue
            if (runStart >= 0 && index - runStart >= minimumQuietFrames) {
                val runEnd = min(end, start + index * frameSamples)
                if (runEnd > endAfter) last = (start + runStart * frameSamples) to runEnd
            }
            runStart = -1
        }
        return last
    }

    /** 20 ms 帧 RMS 高于整段参考值 15%（上限 0.01）的帧计为语音，与 [findQuietRun] 的静音判据互补。 */
    private fun speechSamplesEstimate(samples: FloatArray, start: Int, end: Int): Int {
        val frameSamples = max(1, sampleRate / 50)
        var referenceRms = 0f
        var offset = start
        val frames = mutableListOf<Float>()
        while (offset + frameSamples <= end) {
            val rms = rangeRms(samples, offset, offset + frameSamples)
            frames += rms
            referenceRms = max(referenceRms, rms)
            offset += frameSamples
        }
        if (frames.isEmpty() || referenceRms <= 0f) return 0
        val quietThreshold = min(0.01f, referenceRms * 0.15f)
        return frames.count { it > quietThreshold } * frameSamples
    }

    /**
     * Finish-time departure test.
     *
     * The streaming rule scores the utterance's trailing window, which the owner's own tail keeps
     * above the threshold when the next speaker's turn is shorter than about one window plus one
     * hop, so a short interjection can end up inside the owner's final. At finish the caller scores
     * a short trailing slice instead, where whoever spoke last dominates, and reports it here.
     * A confirmed departure makes [resolveContainment] available; the precise resolver is not used
     * because a finish slice locates no boundary of its own.
     */
    fun observeFinishSlice(score: Float, threshold: Float): Boolean {
        if (!targetSeen || departureSeen || capped || lastTargetEndSample < 0) return false
        if (score >= threshold) return false
        latestScore = score
        if (belowCount < 1) belowCount = 1
        if (firstBelowEndSample < 0) firstBelowEndSample = retainedSamples
        // 收尾切片由调用方对齐到最后一段语音，本身就是带语音的低分证据。
        speechBearingLowScore = true
        departureSeen = true
        resolutionReason = "finish-slice-departure"
        return true
    }

    fun hasPendingFinishDeparture(): Boolean {
        val minimumTrailingSamples = max(1, (sampleRate * 0.4).roundToInt())
        return !departureSeen && !capped && targetSeen && belowCount > 0 &&
            speechBearingLowScore && lastTargetEndSample >= 0 &&
            retainedSamples - lastTargetEndSample >= minimumTrailingSamples
    }

    /**
     * Keep only PCM that predates the last target-positive scoring window.
     *
     * A positive window proves that the target was present somewhere in that window, but it cannot
     * prove that a following speaker did not enter before the window ended. Its start is therefore
     * the latest conservative cut when a confirmed sequential departure has no precise boundary.
     */
    fun resolveContainment(): SpeakerTurnSplit? {
        resolutionReason = "containment-not-ready"
        if (!departureSeen || capped || lastTargetEndSample < 0) {
            if (capped) resolutionReason = "containment-buffer-capped"
            return null
        }
        val cutSample = safePrefixEndSample()
        if (cutSample <= 0 || cutSample >= retainedSamples) {
            resolutionReason = "containment-no-safe-prefix:$cutSample"
            return null
        }
        val all = samples()
        val processed = processedSamples()
        resolutionReason = "containment-safe-prefix:$cutSample"
        return SpeakerTurnSplit(
            cutSample, all.copyOfRange(0, cutSample), all.copyOfRange(cutSample, all.size),
            processed.copyOfRange(0, cutSample), processed.copyOfRange(cutSample, processed.size),
        )
    }

    fun resolve(
        tokenTimestampsSec: List<Float>,
        threshold: Float,
        scoreRange: SpeakerRangeScorer,
        boundaryHintsSamples: List<Int> = emptyList(),
        atFinish: Boolean = false,
    ): SpeakerTurnSplit? {
        resolutionReason = "not-ready"
        pendingCandidatePrefixEndSample = -1
        if (!departureSeen || firstBelowEndSample < 0 || lastTargetEndSample < 0) return null
        if (capped) {
            resolutionReason = "buffer-capped"
            return null
        }
        val all = samples()
        // Window scores locate a transition interval, not an instant. The boundary can be anywhere
        // inside the last target-positive window and must precede the first low-score deadline.
        val searchStart = max(0, lastTargetEndSample - windowSamples)
        val searchEnd = min(all.size, firstBelowEndSample)
        if (searchEnd <= searchStart) {
            resolutionReason = "invalid-search-range"
            return null
        }

        val frameSamples = max(1, (sampleRate / 50.0).roundToInt())
        val refineSamples = windowSamples
        val candidates = mutableListOf<Int>()
        var candidateLackedContext = false
        var strongCandidateLackedRightContext = false
        fun addCandidate(sample: Double, strong: Boolean = false) {
            val candidate = sample.roundToInt()
            if (candidate < searchStart || candidate > searchEnd ||
                candidate <= 0 || candidate >= all.size || candidates.contains(candidate)
            ) return
            if (candidate < refineSamples || all.size - candidate < refineSamples) {
                candidateLackedContext = true
                if (strong && all.size - candidate < refineSamples) {
                    strongCandidateLackedRightContext = true
                }
                return
            }
            candidates += candidate
        }
        for (hint in boundaryHintsSamples) addCandidate(hint.toDouble(), strong = true)
        val hintedCandidateCount = candidates.size
        val quietRun = findQuietRun(all, searchStart, searchEnd, frameSamples)
        if (quietRun != null) {
            addCandidate(
                alignAfterQuietRun(quietRun.first, quietRun.second, tokenTimestampsSec, frameSamples, all.size)
                    .toDouble(),
            )
        }
        val preferredCandidateCount = candidates.size
        val tokenCandidates = mutableListOf<Int>()
        for (timestamp in tokenTimestampsSec) {
            val before = candidates.size
            addCandidate(timestamp.toDouble() * sampleRate, strong = true)
            if (candidates.size > before) tokenCandidates += candidates.last()
        }
        addCandidate((firstBelowEndSample - (windowSamples / 2.0).roundToInt()).toDouble())
        val coarseStep = max(frameSamples, (hopSamples / 2.0).roundToInt())
        var candidate = searchStart
        while (candidate <= searchEnd) {
            addCandidate(candidate.toDouble())
            candidate += coarseStep
        }
        addCandidate(searchEnd.toDouble())
        // A token hint is stronger than the coarse acoustic grid. If its right verification window
        // is still being recorded, wait for that evidence rather than committing an earlier weak
        // candidate that can truncate the target speaker's last phone.
        // 流式时右侧上下文可能还在路上，值得等；收尾时不会再有音频，继续等只会退回保守切点，
        // 把机主整句截短，所以这里跳过等待，用已有候选继续定位。
        if (strongCandidateLackedRightContext && !atFinish) {
            resolutionReason = "insufficient-refine-context"
            return null
        }
        if (candidates.isEmpty()) {
            resolutionReason = if (candidateLackedContext) "insufficient-refine-context" else "no-boundary-candidates"
            return null
        }

        // Rank cheap candidates by sustained left/right waveform contrast and verify at most two with
        // the real target-speaker model, bounding this path to four embedding inferences.
        val hinted = candidates.subList(0, hintedCandidateCount).toMutableList()
        hinted.sortByDescending { transitionContrast(all, it, refineSamples) }
        val preferred = candidates.subList(hintedCandidateCount, preferredCandidateCount).toList()
        val acoustic = candidates.subList(preferredCandidateCount, candidates.size).toMutableList()
        acoustic.sortByDescending { transitionContrast(all, it, refineSamples) }
        // 词边界比能量对比更接近真实换人点：先按"离搜索区间中心最近"排两个 token 候选，
        // 再补保守前缀与能量对比候选，最多校验四个（每个两次 embedding，仍有界）。
        val center = (searchStart + searchEnd) / 2
        val tokenRanked = tokenCandidates.distinct().sortedBy { kotlin.math.abs(it - center) }
        val ranked = (tokenRanked.take(2) + hinted.take(1) + preferred.take(1) + acoustic).distinct()
        val maximumScoredCandidates = 4

        var bestCandidate = -1
        var bestLeft = Float.NEGATIVE_INFINITY
        var bestRight = Float.POSITIVE_INFINITY
        var bestMargin = Float.NEGATIVE_INFINITY
        fun evaluate(point: Int) {
            val leftStart = point - refineSamples
            val rightEnd = point + refineSamples
            val leftScore = scoreRange(all.copyOfRange(leftStart, point), leftStart, point) ?: return
            val rightScore = scoreRange(all.copyOfRange(point, rightEnd), point, rightEnd) ?: return
            if (leftScore < threshold || rightScore >= threshold ||
                leftScore - rightScore < MINIMUM_SPEAKER_SCORE_MARGIN ||
                rightScore > threshold - MINIMUM_NON_TARGET_THRESHOLD_MARGIN + SCORE_EPSILON
            ) return
            val margin = leftScore - rightScore
            if (margin > bestMargin || (margin == bestMargin && point > bestCandidate)) {
                bestCandidate = point
                bestLeft = leftScore
                bestRight = rightScore
                bestMargin = margin
            }
        }
        val scoredCandidateCount = min(maximumScoredCandidates, ranked.size)
        if (scoredCandidateCount > 0) {
            pendingCandidatePrefixEndSample = ranked.subList(0, scoredCandidateCount).min()
        }
        for (index in 0 until scoredCandidateCount) evaluate(ranked[index])
        if (bestCandidate <= 0) {
            resolutionReason = "no-verified-boundary:scored=$scoredCandidateCount,candidates=${candidates.size}"
            return null
        }

        resolutionReason = "split:candidate=$bestCandidate,left=${"%.3f".format(bestLeft)}," +
            "right=${"%.3f".format(bestRight)},margin=${"%.3f".format(bestMargin)}"
        val processed = processedSamples()
        return SpeakerTurnSplit(
            bestCandidate, all.copyOfRange(0, bestCandidate), all.copyOfRange(bestCandidate, all.size),
            processed.copyOfRange(0, bestCandidate), processed.copyOfRange(bestCandidate, processed.size),
        )
    }

    fun reset() {
        parts.clear()
        processedParts.clear()
        retainedSamples = 0
        capped = false
        targetSeen = false
        belowCount = 0
        lastTargetEndSample = -1
        firstBelowEndSample = -1
        lastObservedEndSample = -1
        departureSeen = false
        speechBearingLowScore = false
        rejectBeforeTarget = false
        latestScore = null
        lastTargetScore = null
        resolutionReason = "not-resolved"
        pendingCandidatePrefixEndSample = -1
        preTargetSpeechLowHops = 0
        arrivalWindowStartSample = -1
    }

    private fun findQuietRun(samples: FloatArray, start: Int, end: Int, frameSamples: Int): Pair<Int, Int>? {
        var referenceRms = 0f
        val frames = mutableListOf<Float>()
        var offset = start
        while (offset + frameSamples <= end) {
            val rms = rangeRms(samples, offset, offset + frameSamples)
            frames += rms
            referenceRms = max(referenceRms, rms)
            offset += frameSamples
        }
        if (frames.isEmpty() || referenceRms <= 0f) return null
        val quietThreshold = min(0.01f, referenceRms * 0.15f)
        val minimumQuietFrames = max(1, ceil(sampleRate * 0.08 / frameSamples).toInt())
        var runStart = -1
        var bestStart = -1
        var bestEnd = -1
        for (index in 0..frames.size) {
            val quiet = index < frames.size && frames[index] <= quietThreshold
            if (quiet && runStart < 0) runStart = index
            if (quiet) continue
            if (runStart >= 0 && index - runStart >= minimumQuietFrames) {
                val candidateStart = start + runStart * frameSamples
                val candidateEnd = min(end, start + index * frameSamples)
                if (candidateEnd - candidateStart > bestEnd - bestStart) {
                    bestStart = candidateStart
                    bestEnd = candidateEnd
                }
            }
            runStart = -1
        }
        return if (bestStart >= 0) bestStart to bestEnd else null
    }

    private fun alignAfterQuietRun(
        start: Int,
        end: Int,
        tokenTimestampsSec: List<Float>,
        frameSamples: Int,
        totalSamples: Int,
    ): Int {
        val latestAligned = min(totalSamples - 1, end + frameSamples * 2)
        for (timestamp in tokenTimestampsSec) {
            val token = (timestamp.toDouble() * sampleRate).roundToInt()
            if (token in start..latestAligned) return token
        }
        return end
    }

    private fun transitionContrast(samples: FloatArray, candidate: Int, span: Int): Float {
        val leftStart = max(0, candidate - span)
        val rightEnd = min(samples.size, candidate + span)
        val leftRms = rangeRms(samples, leftStart, candidate)
        val rightRms = rangeRms(samples, candidate, rightEnd)
        val rmsContrast = abs(ln((leftRms + 1e-6f) / (rightRms + 1e-6f)))
        val leftZcr = rangeZeroCrossingRate(samples, leftStart, candidate)
        val rightZcr = rangeZeroCrossingRate(samples, candidate, rightEnd)
        return rmsContrast + abs(leftZcr - rightZcr)
    }

    private companion object {
        const val MINIMUM_SPEAKER_SCORE_MARGIN = 0.15f
        const val MINIMUM_NON_TARGET_THRESHOLD_MARGIN = 0.05f
        const val SCORE_EPSILON = 0.000001f

        fun rangeRms(samples: FloatArray, start: Int, end: Int): Float {
            if (end <= start) return 0f
            var squareSum = 0.0
            for (index in start until end) squareSum += samples[index].toDouble() * samples[index]
            return sqrt(squareSum / (end - start)).toFloat()
        }

        fun rangeZeroCrossingRate(samples: FloatArray, start: Int, end: Int): Float {
            if (end - start < 2) return 0f
            var crossings = 0
            for (index in start + 1 until end) {
                if ((samples[index - 1] < 0f && samples[index] >= 0f) ||
                    (samples[index - 1] >= 0f && samples[index] < 0f)
                ) crossings += 1
            }
            return crossings.toFloat() / (end - start - 1)
        }

        fun concat(parts: List<FloatArray>, total: Int): FloatArray {
            val output = FloatArray(total)
            var offset = 0
            for (part in parts) {
                System.arraycopy(part, 0, output, offset, part.size)
                offset += part.size
            }
            return output
        }
    }
}
