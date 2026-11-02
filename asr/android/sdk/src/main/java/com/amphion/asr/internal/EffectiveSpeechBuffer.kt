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

    /**
     * 同 [acousticallyConfirmed]，但用低得多的 [EffectiveSpeechBuffer.PUBLISH_RMS_THRESHOLD]。
     * 只用于判断文本能不能发布，不参与说话人打分的样本选取。
     */
    var publishSupported = false

    /**
     * 原生 VAD（`Vad.isSpeechDetected()`）确认过这个 run。
     *
     * 与 [externallyConfirmed] 的区别是来源：后者也会被 `asrSpeechConfirmed` 置真，而那来自
     * 识别器自己，拿它去验证识别器的文本是循环论证。本标志只由 [confirmSpeech] 置真。
     */
    var vadConfirmed = false
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
    /** 自上次 reset 以来处理过的 20 ms 窗数。区分"没喂过音频"与"喂过但没有独立证据"。 */
    private var processedWindows = 0
    private var publishRunWindows = 0
    private var publishRunMinRms = Double.POSITIVE_INFINITY
    private var publishRunMaxRms = 0.0

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
            run.vadConfirmed = true
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
        // 非空文本必须有**独立于识别器**的证据才发布。识别器在真人声之后的长静音里会吐出
        // 零散短 token（实测：同一段近似数字静音，前面放 3 秒真人声就出，前面放数字零就
        // 九个电平全不出），而 asrSpeechConfirmed 来自识别器自己，用它验证识别器的文本是
        // 循环论证，所以这里只认声学支撑或原生 VAD。
        // 这里不标记 externallyConfirmed：既然判定这段文本没有独立证据，就不该让它把这个
        // run 变成说话人打分的素材。
        // processedWindows == 0 表示自上次 reset 以来一个窗都没喂过：这时没有判据，而且那段
        // 音频已经在上一次 terminal final 里发布过了，保持原行为放行。幻觉场景不会落到这里，
        // 因为运行时是持续喂音频的（哪怕是近似数字静音，也会产生窗和 run）。
        if (publicText.isNotEmpty() && processedWindows > 0 && !hasIndependentSpeechEvidence()) {
            return EffectiveSpeechFinalDecision(publish = false, samples = FloatArray(0))
        }
        return EffectiveSpeechFinalDecision(
            publish = true,
            samples = take(asrSpeechConfirmed),
        )
    }

    /**
     * 是否存在独立于识别器的语音证据：按 [PUBLISH_RMS_THRESHOLD] 确认的声学 run，或原生
     * VAD 确认过的 run。
     *
     * 声学阈值比 [ACTIVE_RMS_THRESHOLD] 低得多：后者是为说话人打分挑样本调的，实测拿它
     * 决定发布会丢掉 13.3% 的真实远场结果（丁桥 12/90、AISHELL-3 61/500），因为远场语音
     * 整段均值就压在 -40 dBFS 这条线上。
     *
     * 保留 VAD 这一支是因为低音量、恒定包络的真实语音过不了包络起伏那一关，而原生 VAD
     * 是独立信号：实测 Silero（阈值 0.5、窗 512）在客户那段 42.2 秒近似静音上判出 0 段，
     * 在同一文件的真人声上判出 1.38 秒。
     */
    fun hasIndependentSpeechEvidence(): Boolean = runs.any {
        it.windowCount >= REQUIRED_SPEECH_LIKE_WINDOWS && (it.publishSupported || it.vadConfirmed)
    }

    fun reset() {
        samplesInWindow = 0
        runs.clear()
        currentRun = null
        latestRun = null
        retainedSamples = 0
        pendingEvidenceWindows = 0
        windowsSinceLatestRun = Int.MAX_VALUE
        processedWindows = 0
        resetAcousticRun()
        resetPublishRun()
    }

    private fun processWindow(samples: FloatArray) {
        processedWindows += 1
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
            resetPublishRun()
            if (windowsSinceLatestRun != Int.MAX_VALUE) windowsSinceLatestRun += 1
            return
        }

        val edgeSilenceAmplitude = minOf(MAX_EDGE_SILENCE_AMPLITUDE, rms / 4.0)
        val effectiveSamples = trimLongSilentEdges(samples, edgeSilenceAmplitude)
        val run = currentRun ?: EffectiveSpeechRun().also {
            if (pendingEvidenceWindows > 0) {
                // pendingEvidenceWindows 只由 confirmSpeech() 设置，所以这也是 VAD 来源的证据
                it.externallyConfirmed = true
                it.vadConfirmed = true
                pendingEvidenceWindows = 0
            }
            runs += it
            currentRun = it
            latestRun = it
        }
        appendToRun(run, effectiveSamples)
        run.windowCount += 1
        windowsSinceLatestRun = 0

        // 发布支撑的判定必须在下面那个 0.01 的提前返回之前做，否则低于 0.01 的窗就被跳过了。
        // 走到这里 ZCR 已经在区间内，所以只需再比阈值。连续窗数与包络比沿用同一组常量。
        if (rms >= PUBLISH_RMS_THRESHOLD) {
            publishRunWindows += 1
            publishRunMinRms = minOf(publishRunMinRms, rms)
            publishRunMaxRms = maxOf(publishRunMaxRms, rms)
            if (
                publishRunWindows >= REQUIRED_SPEECH_LIKE_WINDOWS &&
                publishRunMaxRms >= publishRunMinRms * MIN_SPEECH_ENERGY_RATIO
            ) {
                run.publishSupported = true
            }
        } else {
            resetPublishRun()
        }

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

    private fun resetPublishRun() {
        publishRunWindows = 0
        publishRunMinRms = Double.POSITIVE_INFINITY
        publishRunMaxRms = 0.0
    }

    internal companion object {
        const val WINDOWS_PER_SECOND = 50
        const val ACTIVE_RMS_THRESHOLD = 0.01

        /**
         * 决定"非空文本能不能发布"的 20 ms 窗 RMS 下限，约 -74 dBFS。
         *
         * 安全带是实测出来的，两头都有余量：
         * - 上沿 -54 dBFS（0.002）：再高就开始丢真实远场语音；-40 dBFS 时丢 13.3%。
         * - 下沿 -89.9 dBFS：客户复现音频里那段近似数字静音的**最大**窗 RMS，阈值高于它才拦得住。
         * 取 -74 dBFS，离上沿 20 dB、离下沿 16 dB。
         *
         * 已知限制：丁桥现场 204 段真实房间静音的最大窗 RMS 中位 -24.4 dBFS、最低 -44.2 dBFS，
         * 远在安全带之上。所以这道门禁挡的是近似数字静音，**挡不住普通房间噪声里的幻觉**。
         */
        const val PUBLISH_RMS_THRESHOLD = 0.0002
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

internal fun speakerScoreMinimumSamples(minSegSec: Float, sampleRate: Int): Int =
    (minSegSec * sampleRate.coerceAtLeast(1)).toInt().coerceAtLeast(0)

internal fun selectSpeakerScoreSamples(
    strictSamples: FloatArray,
    utteranceSamples: FloatArray,
    minSamples: Int,
    asrSpeechConfirmed: Boolean,
): SpeakerScoreSelection {
    val minimum = minSamples.coerceAtLeast(0)
    return when {
        !asrSpeechConfirmed ->
            SpeakerScoreSelection(FloatArray(0), SpeakerScoreSource.INSUFFICIENT)
        minimum > 0 && strictSamples.size >= minimum ->
            SpeakerScoreSelection(strictSamples, SpeakerScoreSource.STRICT)
        // minSegSec=0 removes SDK-side duration judgment, so score the whole real utterance rather
        // than an arbitrarily short strict fragment. A positive value remains only a source preference.
        utteranceSamples.isNotEmpty() ->
            SpeakerScoreSelection(utteranceSamples, SpeakerScoreSource.UTTERANCE)
        strictSamples.isNotEmpty() ->
            SpeakerScoreSelection(strictSamples, SpeakerScoreSource.STRICT)
        else ->
            SpeakerScoreSelection(FloatArray(0), SpeakerScoreSource.INSUFFICIENT)
    }
}

internal fun speakerScoreSelectionDiagnostic(
    selection: SpeakerScoreSelection,
    strictSampleCount: Int,
    utteranceSampleCount: Int,
    minimumSampleCount: Int,
    sampleRate: Int,
    asrSpeechConfirmed: Boolean,
): String {
    val rate = sampleRate.coerceAtLeast(1)
    fun durationMs(samples: Int): Long = samples.coerceAtLeast(0) * 1000L / rate
    return "voiceprint score selection: source=${selection.source.name.lowercase()} " +
        "effectiveSpeechMs=${durationMs(strictSampleCount)} " +
        "utterancePcmMs=${durationMs(utteranceSampleCount)} " +
        "minimumMs=${durationMs(minimumSampleCount)} " +
        "asrEvidence=$asrSpeechConfirmed"
}

internal class RecognizerResetGeneration {
    private var value = 0L

    fun snapshot(): Long = value

    fun markReset() {
        value += 1
    }

    fun changedSince(snapshot: Long): Boolean = value != snapshot
}
