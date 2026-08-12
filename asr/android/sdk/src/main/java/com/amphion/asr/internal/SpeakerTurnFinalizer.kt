package com.amphion.asr.internal

import kotlin.math.ceil
import kotlin.math.roundToInt
import kotlin.math.sqrt

internal enum class SpeakerTurnScoreState {
    WAITING_TARGET,
    TARGET_CONFIRMED,
    TARGET_ACTIVE,
    BELOW,
    PRE_TARGET,
    DEPARTURE,
}

internal data class SpeakerTurnSplit(
    val cutSample: Int,
    val prefix: FloatArray,
    val suffix: FloatArray,
)

internal data class SpeakerTurnSegment(
    val startSample: Int,
    val endSample: Int,
    val speaker: Int,
)

/**
 * Bounded target -> other final-commit state. It never guesses through ambiguous evidence: a split
 * requires consecutive low scores, an acoustic/token boundary, and target-left/non-target-right
 * verification. Returning null is the intentional fail-open path.
 */
internal class SpeakerTurnFinalizer(
    sampleRate: Int,
    windowSamples: Int,
    hopSamples: Int,
    consecutiveBelow: Int,
    maximumSamples: Int,
) {
    private val sampleRate = sampleRate.coerceAtLeast(1)
    private val windowSamples = windowSamples.coerceAtLeast(1)
    private val hopSamples = hopSamples.coerceAtLeast(1)
    private val consecutiveBelow = consecutiveBelow.coerceAtLeast(1)
    private val maximumSamples = maximumSamples.coerceAtLeast(1)
    private val parts = mutableListOf<FloatArray>()
    private var retainedSamples = 0
    private var capped = false
    private var targetSeen = false
    private var belowCount = 0
    private var lastTargetEndSample = -1
    private var firstBelowEndSample = -1
    private var lastObservedEndSample = -1
    private var departureSeen = false
    private var rejectBeforeTarget = false
    private var latestScore: Float? = null
    private var resolutionReason = "not-resolved"

    fun accept(samples: FloatArray) {
        if (samples.isEmpty()) return
        val available = maximumSamples - retainedSamples
        if (samples.size > available) capped = true
        val retained = minOf(samples.size, available.coerceAtLeast(0))
        if (retained > 0) {
            parts += samples.copyOf(retained)
            retainedSamples += retained
        }
    }

    fun observeScore(endSample: Int, score: Float, threshold: Float): SpeakerTurnScoreState {
        lastObservedEndSample = endSample.coerceAtLeast(0)
        latestScore = score
        if (score >= threshold) {
            val firstTarget = !targetSeen
            targetSeen = true
            belowCount = 0
            lastTargetEndSample = endSample.coerceAtLeast(0)
            firstBelowEndSample = -1
            departureSeen = false
            rejectBeforeTarget = false
            return if (firstTarget) {
                SpeakerTurnScoreState.TARGET_CONFIRMED
            } else {
                SpeakerTurnScoreState.TARGET_ACTIVE
            }
        }
        belowCount += 1
        if (!targetSeen) {
            if (belowCount >= consecutiveBelow) {
                rejectBeforeTarget = true
                return SpeakerTurnScoreState.PRE_TARGET
            }
            return SpeakerTurnScoreState.WAITING_TARGET
        }
        if (belowCount == 1) firstBelowEndSample = endSample.coerceAtLeast(0)
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
    fun lastResolutionReason(): String = resolutionReason
    fun needsMoreContext(): Boolean = resolutionReason == "insufficient-refine-context"
    fun hasPendingDeparture(): Boolean = departureSeen

    fun resolve(
        tokenTimestampsSec: FloatArray,
        threshold: Float,
        scoreRange: (samples: FloatArray, startSample: Int, endSample: Int) -> Float?,
    ): SpeakerTurnSplit? = resolve(tokenTimestampsSec, threshold, intArrayOf(), scoreRange)

    fun resolve(
        tokenTimestampsSec: FloatArray,
        threshold: Float,
        boundaryHintsSamples: IntArray,
        scoreRange: (samples: FloatArray, startSample: Int, endSample: Int) -> Float?,
    ): SpeakerTurnSplit? {
        resolutionReason = "not-ready"
        if (!departureSeen || firstBelowEndSample < 0 || lastTargetEndSample < 0) return null
        if (capped) {
            resolutionReason = "buffer-capped"
            return null
        }
        val all = concatParts()
        // A score describes a window, not a point. Search the evidence-derived transition band.
        val searchStart = (lastTargetEndSample - windowSamples).coerceAtLeast(0)
        val stableOtherStart = (lastObservedEndSample - windowSamples).coerceAtLeast(0)
        val searchEnd = minOf(
            all.size,
            firstBelowEndSample,
            stableOtherStart + hopSamples,
        )
        if (searchEnd <= searchStart) {
            resolutionReason = "invalid-search-range"
            return null
        }

        val frameSamples = (sampleRate / 50.0).roundToInt().coerceAtLeast(1)
        val refineSamples = windowSamples
        if (searchStart < refineSamples || all.size - searchEnd < refineSamples) {
            resolutionReason = "insufficient-refine-context"
            return null
        }
        val candidates = mutableListOf<Int>()
        fun addCandidate(sample: Int) {
            val candidate = sample.coerceAtLeast(0)
            if (candidate !in searchStart..searchEnd || candidate <= 0 ||
                candidate >= all.size || candidate in candidates
            ) {
                return
            }
            candidates += candidate
        }
        boundaryHintsSamples.forEach(::addCandidate)
        val hintedCandidateCount = candidates.size
        val quietRun = findQuietRun(all, searchStart, searchEnd, frameSamples)
        if (quietRun != null) {
            addCandidate(alignAfterQuietRun(
                quietRun.first,
                quietRun.second,
                tokenTimestampsSec,
                frameSamples,
                all.size,
            ))
        }
        val preferredCandidateCount = candidates.size
        tokenTimestampsSec.forEach { timestamp ->
            addCandidate((timestamp * sampleRate).roundToInt())
        }
        addCandidate(firstBelowEndSample - windowSamples / 2)
        val coarseStep = maxOf(frameSamples, hopSamples / 2)
        var candidate = searchStart
        while (candidate <= searchEnd) {
            addCandidate(candidate)
            candidate += coarseStep
        }
        addCandidate(searchEnd)

        // Keep parity with Harmony's bounded synchronous inference path. Candidate generation is
        // cheap and deterministic; only the two strongest candidates reach the speaker model.
        val hinted = candidates.take(hintedCandidateCount)
            .sortedByDescending { transitionContrast(all, it, refineSamples) }
        val preferred = candidates.drop(hintedCandidateCount)
            .take(preferredCandidateCount - hintedCandidateCount)
        val acoustic = candidates.drop(preferredCandidateCount)
            .sortedByDescending { transitionContrast(all, it, refineSamples) }
        val ranked = hinted.take(1) + preferred.take(1) + acoustic
        val maximumScoredCandidates = 2

        var bestCandidate = -1
        var bestLeft = Float.NEGATIVE_INFINITY
        var bestRight = Float.POSITIVE_INFINITY
        var bestMargin = Float.NEGATIVE_INFINITY
        fun evaluate(current: Int) {
            val leftStart = current - refineSamples
            val rightEnd = current + refineSamples
            val leftScore = scoreRange(
                all.copyOfRange(leftStart, current),
                leftStart,
                current,
            ) ?: return
            val rightScore = scoreRange(
                all.copyOfRange(current, rightEnd),
                current,
                rightEnd,
            ) ?: return
            if (leftScore < threshold || rightScore >= threshold) return
            val margin = leftScore - rightScore
            if (margin > bestMargin || (margin == bestMargin && current > bestCandidate)) {
                bestCandidate = current
                bestLeft = leftScore
                bestRight = rightScore
                bestMargin = margin
            }
        }
        val scoredCandidateCount = minOf(maximumScoredCandidates, ranked.size)
        ranked.take(scoredCandidateCount).forEach(::evaluate)
        if (bestCandidate <= 0) {
            resolutionReason = "no-verified-boundary:scored=$scoredCandidateCount," +
                "candidates=${candidates.size}"
            return null
        }

        resolutionReason = "split:candidate=$bestCandidate,left=${formatScore(bestLeft)}," +
            "right=${formatScore(bestRight)},margin=${formatScore(bestMargin)}"
        return SpeakerTurnSplit(
            cutSample = bestCandidate,
            prefix = all.copyOfRange(0, bestCandidate),
            suffix = all.copyOfRange(bestCandidate, all.size),
        )
    }

    /** Resolve the last stable, non-overlapping target -> other turn reported by diarization. */
    fun resolveDiarized(
        segments: List<SpeakerTurnSegment>,
        threshold: Float,
        scoreCluster: (samples: FloatArray, speaker: Int) -> Float?,
    ): SpeakerTurnSplit? {
        resolutionReason = "diarization-not-ready"
        if (!departureSeen || capped) {
            if (capped) resolutionReason = "buffer-capped"
            return null
        }
        val all = concatParts()
        val minimumStableSamples = (sampleRate * 0.2f).roundToInt().coerceAtLeast(1)
        val stable = segments
            .map { segment ->
                SpeakerTurnSegment(
                    startSample = segment.startSample.coerceIn(0, all.size),
                    endSample = segment.endSample.coerceIn(0, all.size),
                    speaker = segment.speaker,
                )
            }
            .filter { segment -> segment.endSample - segment.startSample >= minimumStableSamples }
            .sortedWith(compareBy<SpeakerTurnSegment> { it.startSample }.thenBy { it.endSample })
        if (stable.size < 2) {
            resolutionReason = "diarization-insufficient-segments"
            return null
        }
        stable.zipWithNext().forEach { (left, right) ->
            if (left.speaker != right.speaker && right.startSample < left.endSample) {
                resolutionReason = "unsupported-overlap"
                return null
            }
        }
        val speakerIds = stable.map { it.speaker }.distinct()
        if (speakerIds.size != 2) {
            resolutionReason = "diarization-speaker-count:${speakerIds.size}"
            return null
        }
        val scores = mutableMapOf<Int, Float>()
        speakerIds.forEach { speaker ->
            val score = scoreCluster(concatSpeakerSegments(all, stable, speaker), speaker)
            if (score == null) {
                resolutionReason = "diarization-score-unavailable:$speaker"
                return null
            }
            scores[speaker] = score
        }
        val targetIds = speakerIds.filter { speaker -> scores.getValue(speaker) >= threshold }
        if (targetIds.size != 1) {
            resolutionReason = "diarization-target-count:${targetIds.size}"
            return null
        }
        val targetSpeaker = targetIds.single()
        val candidate = stable.zipWithNext()
            .filter { (left, right) -> left.speaker == targetSpeaker && right.speaker != targetSpeaker }
            .lastOrNull()
            ?.second
            ?.startSample
            ?: -1
        if (candidate <= 0 || candidate >= all.size) {
            resolutionReason = "diarization-no-sequential-departure"
            return null
        }
        // Scores describe trailing windows rather than point-in-time states. A real change may be
        // anywhere in the last target-positive window, but never before that window starts.
        val transitionStart = (lastTargetEndSample - windowSamples).coerceAtLeast(0)
        val transitionEnd = lastTargetEndSample.coerceAtMost(all.size)
        if (transitionEnd <= transitionStart || candidate !in transitionStart..transitionEnd) {
            resolutionReason = "diarization-outside-score-transition:$candidate:not-in:" +
                "$transitionStart-$transitionEnd"
            return null
        }
        val otherSpeaker = speakerIds.single { it != targetSpeaker }
        resolutionReason = "diarization-split:left=${formatScore(scores.getValue(targetSpeaker))}," +
            "right=${formatScore(scores.getValue(otherSpeaker))}"
        return SpeakerTurnSplit(
            cutSample = candidate,
            prefix = all.copyOfRange(0, candidate),
            suffix = all.copyOfRange(candidate, all.size),
        )
    }

    fun reset() {
        parts.clear()
        retainedSamples = 0
        capped = false
        targetSeen = false
        belowCount = 0
        lastTargetEndSample = -1
        firstBelowEndSample = -1
        lastObservedEndSample = -1
        departureSeen = false
        rejectBeforeTarget = false
        latestScore = null
        resolutionReason = "not-resolved"
    }

    private fun findQuietRun(
        samples: FloatArray,
        start: Int,
        end: Int,
        frameSamples: Int,
    ): Pair<Int, Int>? {
        val frames = mutableListOf<Double>()
        var referenceRms = 0.0
        var offset = start
        while (offset + frameSamples <= end) {
            val rms = rangeRms(samples, offset, offset + frameSamples)
            frames += rms
            referenceRms = maxOf(referenceRms, rms)
            offset += frameSamples
        }
        if (frames.isEmpty() || referenceRms <= 0.0) return null
        val quietThreshold = minOf(0.01, referenceRms * 0.15)
        val minimumQuietFrames = ceil(sampleRate * 0.08 / frameSamples).toInt().coerceAtLeast(1)
        var runStart = -1
        var bestStart = -1
        var bestEnd = -1
        for (index in 0..frames.size) {
            val quiet = index < frames.size && frames[index] <= quietThreshold
            if (quiet && runStart < 0) runStart = index
            if (quiet) continue
            if (runStart >= 0 && index - runStart >= minimumQuietFrames) {
                val candidateStart = start + runStart * frameSamples
                val candidateEnd = minOf(end, start + index * frameSamples)
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
        tokenTimestampsSec: FloatArray,
        frameSamples: Int,
        totalSamples: Int,
    ): Int {
        val latestAligned = minOf(totalSamples - 1, end + frameSamples * 2)
        for (timestamp in tokenTimestampsSec) {
            val tokenSample = (timestamp * sampleRate).roundToInt()
            if (tokenSample in start..latestAligned) return tokenSample
        }
        return end
    }

    private fun transitionContrast(samples: FloatArray, candidate: Int, span: Int): Double {
        val leftStart = (candidate - span).coerceAtLeast(0)
        val rightEnd = (candidate + span).coerceAtMost(samples.size)
        val leftRms = rangeRms(samples, leftStart, candidate)
        val rightRms = rangeRms(samples, candidate, rightEnd)
        val rmsContrast = kotlin.math.abs(kotlin.math.ln((leftRms + 1e-6) / (rightRms + 1e-6)))
        val leftZcr = rangeZeroCrossingRate(samples, leftStart, candidate)
        val rightZcr = rangeZeroCrossingRate(samples, candidate, rightEnd)
        return rmsContrast + kotlin.math.abs(leftZcr - rightZcr)
    }

    private fun rangeZeroCrossingRate(samples: FloatArray, start: Int, end: Int): Double {
        if (end - start < 2) return 0.0
        var crossings = 0
        for (index in start + 1 until end) {
            if ((samples[index - 1] < 0f && samples[index] >= 0f) ||
                (samples[index - 1] >= 0f && samples[index] < 0f)
            ) {
                crossings += 1
            }
        }
        return crossings.toDouble() / (end - start - 1)
    }

    private fun scoreChangeTokenBoundary(
        tokenTimestampsSec: FloatArray,
        searchStart: Int,
        searchEnd: Int,
    ): Int {
        val estimate = (firstBelowEndSample - windowSamples / 2).coerceIn(searchStart, searchEnd)
        val latest = minOf(searchEnd + hopSamples, retainedSamples - 1)
        for (timestamp in tokenTimestampsSec) {
            val tokenSample = (timestamp * sampleRate).roundToInt()
            if (tokenSample in estimate..latest) return tokenSample
        }
        return -1
    }

    private fun concatParts(): FloatArray {
        val output = FloatArray(retainedSamples)
        var offset = 0
        for (part in parts) {
            System.arraycopy(part, 0, output, offset, part.size)
            offset += part.size
        }
        return output
    }

    private fun concatSpeakerSegments(
        samples: FloatArray,
        segments: List<SpeakerTurnSegment>,
        speaker: Int,
    ): FloatArray {
        val selected = segments.filter { it.speaker == speaker }
        val output = FloatArray(selected.sumOf { it.endSample - it.startSample })
        var offset = 0
        selected.forEach { segment ->
            samples.copyInto(output, offset, segment.startSample, segment.endSample)
            offset += segment.endSample - segment.startSample
        }
        return output
    }

    private fun rangeRms(samples: FloatArray, start: Int, end: Int): Double {
        var squareSum = 0.0
        for (index in start until end) squareSum += samples[index] * samples[index]
        return if (end > start) sqrt(squareSum / (end - start)) else 0.0
    }

    private fun formatScore(score: Float): String = "%.3f".format(java.util.Locale.US, score)
}
