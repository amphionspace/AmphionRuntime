package com.amphion.asr.internal

import kotlin.math.abs
import kotlin.math.roundToInt
import kotlin.math.sqrt

internal data class EffectiveSpeechFinalDecision(
    val publish: Boolean,
    val samples: FloatArray,
)

private class EffectiveSpeechRun {
    val parts = mutableListOf<FloatArray>()
    var sampleCount = 0
    var windowCount = 0
    var acousticallyConfirmed = false
    var externallyConfirmed = false
}

/**
 * Selects fixed 20 ms speech-shaped windows for final speaker scoring.
 *
 * Native VAD or ASR evidence may admit a low-volume, constant-envelope candidate, but the evidence
 * remains bound to one contiguous run. Without external evidence, envelope movement is required so
 * steady high-energy non-speech cannot become scoreable speech.
 */
internal class EffectiveSpeechBuffer(
    sampleRate: Int,
    maxSamples: Int,
) {
    private val window = FloatArray((sampleRate / WINDOWS_PER_SECOND).coerceAtLeast(1))
    private val maximumSamples = maxSamples.coerceAtLeast(0)
    private val minimumEdgeSilenceSamples =
        (sampleRate * MIN_EDGE_SILENCE_MS / 1000.0).roundToInt().coerceAtLeast(1)

    private var samplesInWindow = 0
    private val runs = mutableListOf<EffectiveSpeechRun>()
    private var currentRun: EffectiveSpeechRun? = null
    private var latestRun: EffectiveSpeechRun? = null
    private var retainedSamples = 0
    private var pendingEvidenceWindows = 0
    private var windowsSinceLatestRun = Int.MAX_VALUE
    private var acousticRunWindows = 0
    private var acousticRunMinRms = Double.POSITIVE_INFINITY
    private var acousticRunMaxRms = 0.0

    fun observe(samples: FloatArray) {
        var offset = 0
        while (offset < samples.size) {
            val count = minOf(samples.size - offset, window.size - samplesInWindow)
            System.arraycopy(samples, offset, window, samplesInWindow, count)
            samplesInWindow += count
            offset += count
            if (samplesInWindow == window.size) {
                processWindow(window.copyOf())
                samplesInWindow = 0
            }
        }
    }

    fun confirmSpeech() {
        val run = currentRun ?: latestRun?.takeIf {
            windowsSinceLatestRun <= MAX_VAD_EVIDENCE_LAG_WINDOWS
        }
        if (run != null) {
            run.externallyConfirmed = true
        } else {
            pendingEvidenceWindows = MAX_VAD_EVIDENCE_LAG_WINDOWS
        }
    }

    fun take(asrSpeechConfirmed: Boolean = false): FloatArray {
        if (asrSpeechConfirmed) latestRun?.externallyConfirmed = true
        val output = collectConfirmedRuns()
        reset()
        return output
    }

    fun resolveFinal(
        publicText: String,
        asrSpeechConfirmed: Boolean,
        isLast: Boolean,
    ): EffectiveSpeechFinalDecision {
        if (publicText.isEmpty() && !isLast) {
            if (asrSpeechConfirmed) latestRun?.externallyConfirmed = true
            return EffectiveSpeechFinalDecision(publish = false, samples = FloatArray(0))
        }
        return EffectiveSpeechFinalDecision(
            publish = true,
            samples = take(asrSpeechConfirmed),
        )
    }

    fun reset() {
        samplesInWindow = 0
        runs.clear()
        currentRun = null
        latestRun = null
        retainedSamples = 0
        pendingEvidenceWindows = 0
        windowsSinceLatestRun = Int.MAX_VALUE
        resetAcousticRun()
    }

    private fun processWindow(samples: FloatArray) {
        if (pendingEvidenceWindows > 0) pendingEvidenceWindows -= 1
        if (retainedSamples >= maximumSamples) return

        var squareSum = 0.0
        var zeroCrossings = 0
        for (index in samples.indices) {
            val sample = samples[index]
            squareSum += sample * sample
            if (index > 0 && (sample >= 0.0f) != (samples[index - 1] >= 0.0f)) {
                zeroCrossings += 1
            }
        }
        val rms = sqrt(squareSum / samples.size)
        val zeroCrossingRate = zeroCrossings.toDouble() / (samples.size - 1).coerceAtLeast(1)
        val evidenceCandidate = rms > 0.0 &&
            zeroCrossingRate in MIN_SPEECH_ZCR..MAX_SPEECH_ZCR
        if (!evidenceCandidate) {
            currentRun = null
            resetAcousticRun()
            if (windowsSinceLatestRun != Int.MAX_VALUE) windowsSinceLatestRun += 1
            return
        }

        val edgeSilenceAmplitude = minOf(MAX_EDGE_SILENCE_AMPLITUDE, rms / 4.0)
        val effectiveSamples = trimLongSilentEdges(samples, edgeSilenceAmplitude)
        val run = currentRun ?: EffectiveSpeechRun().also {
            if (pendingEvidenceWindows > 0) {
                it.externallyConfirmed = true
                pendingEvidenceWindows = 0
            }
            runs += it
            currentRun = it
            latestRun = it
        }
        appendToRun(run, effectiveSamples)
        run.windowCount += 1
        windowsSinceLatestRun = 0

        if (rms < ACTIVE_RMS_THRESHOLD || zeroCrossingRate !in MIN_SPEECH_ZCR..MAX_SPEECH_ZCR) {
            resetAcousticRun()
            return
        }
        acousticRunWindows += 1
        acousticRunMinRms = minOf(acousticRunMinRms, rms)
        acousticRunMaxRms = maxOf(acousticRunMaxRms, rms)
        if (
            acousticRunWindows >= REQUIRED_SPEECH_LIKE_WINDOWS &&
            acousticRunMaxRms >= acousticRunMinRms * MIN_SPEECH_ENERGY_RATIO
        ) {
            run.acousticallyConfirmed = true
        }
    }

    private fun appendToRun(run: EffectiveSpeechRun, samples: FloatArray) {
        val remaining = maximumSamples - retainedSamples
        if (remaining <= 0) return
        val retained = if (samples.size <= remaining) samples else samples.copyOf(remaining)
        run.parts += retained
        run.sampleCount += retained.size
        retainedSamples += retained.size
    }

    private fun collectConfirmedRuns(): FloatArray {
        val confirmed = runs.filter {
            it.windowCount >= REQUIRED_SPEECH_LIKE_WINDOWS &&
                (it.externallyConfirmed || it.acousticallyConfirmed)
        }
        val output = FloatArray(confirmed.sumOf { it.sampleCount })
        var offset = 0
        for (run in confirmed) {
            for (part in run.parts) {
                System.arraycopy(part, 0, output, offset, part.size)
                offset += part.size
            }
        }
        return output
    }

    private fun trimLongSilentEdges(samples: FloatArray, silenceAmplitude: Double): FloatArray {
        var start = 0
        while (start < samples.size && abs(samples[start]) < silenceAmplitude) start += 1
        if (start < minimumEdgeSilenceSamples) start = 0

        var end = samples.size
        while (end > start && abs(samples[end - 1]) < silenceAmplitude) end -= 1
        if (samples.size - end < minimumEdgeSilenceSamples) end = samples.size
        return if (start == 0 && end == samples.size) {
            samples
        } else {
            samples.copyOfRange(start, end)
        }
    }

    private fun resetAcousticRun() {
        acousticRunWindows = 0
        acousticRunMinRms = Double.POSITIVE_INFINITY
        acousticRunMaxRms = 0.0
    }

    private companion object {
        const val WINDOWS_PER_SECOND = 50
        const val ACTIVE_RMS_THRESHOLD = 0.01
        const val MIN_SPEECH_ZCR = 0.005
        const val MAX_SPEECH_ZCR = 0.35
        const val REQUIRED_SPEECH_LIKE_WINDOWS = 3
        const val MIN_SPEECH_ENERGY_RATIO = 3.0
        const val MIN_EDGE_SILENCE_MS = 5
        const val MAX_EDGE_SILENCE_AMPLITUDE = ACTIVE_RMS_THRESHOLD / 2
        const val MAX_VAD_EVIDENCE_LAG_WINDOWS = 3
    }
}

internal enum class SpeakerScoreSource {
    STRICT,
    UTTERANCE,
    INSUFFICIENT,
}

internal data class SpeakerScoreSelection(
    val samples: FloatArray,
    val source: SpeakerScoreSource,
)

internal fun selectSpeakerScoreSamples(
    strictSamples: FloatArray,
    utteranceSamples: FloatArray,
    minSamples: Int,
    asrSpeechConfirmed: Boolean,
): SpeakerScoreSelection {
    val minimum = minSamples.coerceAtLeast(1)
    return when {
        strictSamples.size >= minimum ->
            SpeakerScoreSelection(strictSamples, SpeakerScoreSource.STRICT)
        asrSpeechConfirmed && utteranceSamples.size >= minimum ->
            SpeakerScoreSelection(utteranceSamples, SpeakerScoreSource.UTTERANCE)
        else ->
            SpeakerScoreSelection(strictSamples, SpeakerScoreSource.INSUFFICIENT)
    }
}

internal class RecognizerResetGeneration {
    private var value = 0L

    fun snapshot(): Long = value

    fun markReset() {
        value += 1
    }

    fun changedSince(snapshot: Long): Boolean = value != snapshot
}
