package com.lits.tts.sdk.internal

import android.content.Context
import android.util.Log
import com.lits.tts.sdk.CreateEngineParams
import com.lits.tts.sdk.SpeakParams
import com.lits.tts.sdk.TtsErrorCode
import kotlin.math.PI
import kotlin.math.roundToInt
import kotlin.math.sin

internal data class SynthesizedAudio(
    val pcm: ByteArray,
    val sampleRate: Int,
    val synthesisMs: Long = -1L,
    val audioBytes: Long = pcm.size.toLong(),
    val firstChunkMs: Long = -1L,
    val profilingInfo: String = "",
)

internal interface PcmSynthesizer {
    fun preload()

    fun synthesize(text: String, params: SpeakParams, engineParams: CreateEngineParams): SynthesizedAudio

    fun supportsStreamingSynthesis(): Boolean = false

    fun canStream(params: SpeakParams, engineParams: CreateEngineParams): Boolean = supportsStreamingSynthesis()

    fun streamingSampleRate(engineParams: CreateEngineParams): Int? = null

    fun streamingChunkSize(params: SpeakParams, engineParams: CreateEngineParams): Int? = null

    fun synthesizeStreaming(
        text: String,
        params: SpeakParams,
        engineParams: CreateEngineParams,
        collectOutput: Boolean = true,
        isCancelled: () -> Boolean = { false },
        onChunk: (ByteArray) -> Unit,
    ): SynthesizedAudio = synthesize(text, params, engineParams).also { onChunk(it.pcm) }

    fun supportsInternalPlayback(): Boolean = true

    fun debugSummary(): String = "source=unknown model=unknown"

    fun loadProfileInfo(): String = ""

    fun close() = Unit
}

internal class DeterministicPcmSynthesizer : PcmSynthesizer {
    override fun preload() = Unit

    override fun supportsInternalPlayback(): Boolean = false

    override fun streamingSampleRate(engineParams: CreateEngineParams): Int = SAMPLE_RATE

    override fun synthesize(text: String, params: SpeakParams, engineParams: CreateEngineParams): SynthesizedAudio {
        val startedAt = System.nanoTime()
        val durationMs = (text.length * 40).coerceIn(160, 2000)
        val sampleCount = SAMPLE_RATE * durationMs / 1000
        val base = ShortArray(sampleCount)
        val frequency = if (engineParams.language == "en-US") 440.0 else 330.0
        val amplitude = (Short.MAX_VALUE * 0.12f).toInt()
        for (index in 0 until sampleCount) {
            val sample = (sin(2.0 * PI * frequency * index / SAMPLE_RATE) * amplitude).toInt()
            base[index] = sample.toShort()
        }
        val pcm = AudioTransforms.apply(base, params)
        return SynthesizedAudio(
            pcm = shortsToBytes(pcm),
            sampleRate = SAMPLE_RATE,
            synthesisMs = (System.nanoTime() - startedAt) / 1_000_000L,
        )
    }

    private companion object {
        const val SAMPLE_RATE = 24000
    }
}

internal class LitsDeliveryPcmSynthesizer(
    private val context: Context,
    private val workPath: String?,
    private val speakerId: Int,
) : PcmSynthesizer {
    private companion object {
        private const val FRONTEND_REQUEST_TAG = "LitsFrontendRequest"

        fun logFrontendRequest(message: String) {
            runCatching { Log.i(FRONTEND_REQUEST_TAG, message) }
        }
    }

    @Volatile
    private var layout: LitsTtsAssetInstaller.InstalledLayout? = null

    @Volatile
    private var runtime: LitsTtsOrtRuntime? = null

    @Volatile
    private var loadProfileInfo: String = ""

    override fun preload() {
        val layoutStartedAt = System.nanoTime()
        val activeLayout = ensureLayout()
        val layoutMs = elapsedMs(layoutStartedAt)
        val frontendStartedAt = System.nanoTime()
        LitsTtsFrontend.preload(activeLayout)
        val frontendMs = elapsedMs(frontendStartedAt)
        val runtimeStartedAt = System.nanoTime()
        val activeRuntime = obtainRuntime(activeLayout)
        val runtimeMs = elapsedMs(runtimeStartedAt)
        loadProfileInfo = buildLoadProfile(layoutMs, frontendMs, runtimeMs, activeRuntime.loadProfileInfo)
    }

    override fun synthesize(text: String, params: SpeakParams, engineParams: CreateEngineParams): SynthesizedAudio {
        val startedAt = System.nanoTime()
        val activeLayout = layout ?: throw notReady()
        val activeRuntime = runtime ?: throw notReady()
        logFrontendRequest(
            "synthesize start language=${engineParams.language} languageContext=${params.languageContext} textLen=${text.length} text=$text",
        )
        val tokenIds = LitsTtsFrontend.encode(activeLayout, text, engineParams.language, params.languageContext)
        logFrontendRequest(
            "synthesize frontend tokenCount=${tokenIds.size} tokenIds=${tokenIds.joinToString(" ")}",
        )
        val waveform = activeRuntime.synthesize(tokenIds, speakerId)
        val pcm = AudioTransforms.apply(LitsTtsOrtRuntime.floatToPcm16(waveform), params)
        val synthesisMs = (System.nanoTime() - startedAt) / 1_000_000L
        logFrontendRequest(
            "synthesize complete synthesisMs=$synthesisMs pcmBytes=${pcm.size * 2}",
        )
        return SynthesizedAudio(
            pcm = shortsToBytes(pcm),
            sampleRate = activeLayout.manifest.sampleRate,
            synthesisMs = synthesisMs,
        )
    }

    override fun supportsStreamingSynthesis(): Boolean = ensureLayout().manifest.supportsStreaming

    override fun canStream(params: SpeakParams, engineParams: CreateEngineParams): Boolean {
        val manifest = ensureLayout().manifest
        return manifest.supportsStreaming
    }

    override fun streamingSampleRate(engineParams: CreateEngineParams): Int = ensureLayout().manifest.sampleRate

    override fun streamingChunkSize(params: SpeakParams, engineParams: CreateEngineParams): Int {
        val manifest = ensureLayout().manifest
        return streamingChunkSizeOverride(params) ?: manifest.streamingChunkSize
    }

    override fun debugSummary(): String = ensureLayout().debugSummary()

    override fun loadProfileInfo(): String = loadProfileInfo

    override fun synthesizeStreaming(
        text: String,
        params: SpeakParams,
        engineParams: CreateEngineParams,
        collectOutput: Boolean,
        isCancelled: () -> Boolean,
        onChunk: (ByteArray) -> Unit,
    ): SynthesizedAudio {
        if (!supportsStreamingSynthesis()) {
            return synthesize(text, params, engineParams).also { onChunk(it.pcm) }
        }
        val startedAt = System.nanoTime()
        val activeLayout = layout ?: throw notReady()
        val activeRuntime = runtime ?: throw notReady()
        val lengthScale = lengthScaleForSpeed(params.speed)
        logFrontendRequest(
            "stream start language=${engineParams.language} languageContext=${params.languageContext} speed=${params.speed} lengthScale=$lengthScale textLen=${text.length} text=$text",
        )
        val textSegments = LitsTtsFrontend.splitForStreaming(
            layout = activeLayout,
            text = text,
            language = engineParams.language,
            languageContext = params.languageContext,
        )
        logFrontendRequest("stream segments count=${textSegments.size} segments=${textSegments.joinToString(" | ")}")
        val output = if (collectOutput) java.io.ByteArrayOutputStream() else null
        var totalBytes = 0L
        var firstChunkMs = -1L
        var frontendMs = 0L
        var firstPacketFrontendMs = -1L
        var runtimeMetrics: LitsTtsOrtRuntime.StreamingRuntimeMetrics? = null
        val chunkSizeOverride = streamingChunkSizeOverride(params)
        val firstChunkSizeOverride = streamingFirstChunkSizeOverride(params)
        for (segment in textSegments) {
            if (isCancelled()) {
                break
            }
            val frontendStartedAt = System.nanoTime()
            val tokenIds = LitsTtsFrontend.encodeNormalized(activeLayout, segment, engineParams.language, params.languageContext)
            if (isCancelled()) {
                break
            }
            val segmentFrontendMs = elapsedMs(frontendStartedAt)
            logFrontendRequest(
                "stream segment frontendMs=$segmentFrontendMs tokenCount=${tokenIds.size} segment=$segment tokenIds=${tokenIds.joinToString(" ")}",
            )
            frontendMs += segmentFrontendMs
            if (firstPacketFrontendMs < 0L) firstPacketFrontendMs = segmentFrontendMs
            val segmentMetrics = activeRuntime.synthesizeStreaming(
                tokenIds = tokenIds,
                speakerId = speakerId,
                manifest = activeLayout.manifest,
                lengthScale = lengthScale,
                chunkSizeOverride = chunkSizeOverride,
                firstChunkSizeOverride = firstChunkSizeOverride,
                isCancelled = isCancelled,
            ) { waveformChunk ->
                if (!isCancelled()) {
                    val pcmChunk = shortsToBytes(AudioTransforms.applyPitchAndVolume(LitsTtsOrtRuntime.floatToPcm16(waveformChunk), params))
                    if (firstChunkMs < 0L) firstChunkMs = elapsedMs(startedAt)
                    output?.write(pcmChunk)
                    totalBytes += pcmChunk.size.toLong()
                    onChunk(pcmChunk)
                }
            }
            runtimeMetrics = runtimeMetrics?.plus(segmentMetrics) ?: segmentMetrics
        }
        val synthesisMs = elapsedMs(startedAt)
        logFrontendRequest(
            "stream complete synthesisMs=$synthesisMs frontendMs=$frontendMs totalBytes=$totalBytes firstChunkMs=$firstChunkMs",
        )
        return SynthesizedAudio(
            pcm = output?.toByteArray() ?: ByteArray(0),
            sampleRate = activeLayout.manifest.sampleRate,
            synthesisMs = synthesisMs,
            audioBytes = totalBytes,
            firstChunkMs = firstChunkMs,
            profilingInfo = buildStreamingProfile(
                frontendMs = frontendMs,
                runtimeMetrics = runtimeMetrics,
                textSegments = textSegments.size,
                firstPacketMs = firstChunkMs,
                firstPacketFrontendMs = firstPacketFrontendMs,
            ),
        )
    }

    override fun close() {
        resetRuntime()
    }

    private fun ensureLayout(): LitsTtsAssetInstaller.InstalledLayout {
        val cached = layout
        if (cached != null) return cached
        return LitsTtsAssetInstaller.ensureInstalled(context, workPath).also { layout = it }
    }

    private fun obtainRuntime(layout: LitsTtsAssetInstaller.InstalledLayout): LitsTtsOrtRuntime {
        val cached = runtime
        if (cached != null) return cached
        return LitsTtsOrtRuntime(layout).also { runtime = it }
    }

    private fun resetRuntime() {
        try {
            runtime?.close()
        } catch (_: Throwable) {
        } finally {
            runtime = null
        }
    }

    private fun notReady(): IllegalStateException =
        IllegalStateException("${TtsErrorCode.ENGINE_NOT_INITIALIZED}:TTS engine is not ready")

    private fun buildStreamingProfile(
        frontendMs: Long,
        runtimeMetrics: LitsTtsOrtRuntime.StreamingRuntimeMetrics?,
        textSegments: Int,
        firstPacketMs: Long,
        firstPacketFrontendMs: Long,
    ): String = buildString {
        append("frontend=").append(frontendMs).append("ms")
        append(" textSegments=").append(textSegments)
        if (runtimeMetrics == null) return@buildString
        append(" firstPacketBreakdown=").append(
            formatFirstPacketBreakdown(
                firstPacketMs = firstPacketMs,
                frontendMs = firstPacketFrontendMs,
                hiddenMs = runtimeMetrics.firstHiddenEncoderMs,
                decoderMs = runtimeMetrics.firstDecoderMs,
                vocoderMs = runtimeMetrics.firstVocoderMs,
            ),
        )
        append(" onnxHiddenEncoder=").append(formatModuleTiming(runtimeMetrics.hiddenEncoderMs, runtimeMetrics.hiddenEncoderCalls))
        append(" onnxStreamDecoderChunk=").append(formatModuleTiming(runtimeMetrics.decoderMs, runtimeMetrics.decoderCalls))
        append(" onnxVocoder=").append(formatModuleTiming(runtimeMetrics.vocoderMs, runtimeMetrics.vocoderCalls))
        append(" chunks=").append(runtimeMetrics.chunkCount)
        append(" melLength=").append(runtimeMetrics.melLength)
        append(" chunkSize=").append(runtimeMetrics.chunkSize)
        if (runtimeMetrics.firstChunkSize != runtimeMetrics.chunkSize) {
            append(" firstChunkSize=").append(runtimeMetrics.firstChunkSize)
        }
        append(" finalDecoder=").append(runtimeMetrics.finalDecoderMode)
        append(" runtimeFirstChunk=").append(runtimeMetrics.firstChunkMs).append("ms")
    }

    private fun formatFirstPacketBreakdown(
        firstPacketMs: Long,
        frontendMs: Long,
        hiddenMs: Long,
        decoderMs: Long,
        vocoderMs: Long,
    ): String {
        val knownMs = listOf(frontendMs, hiddenMs, decoderMs, vocoderMs)
            .filter { it >= 0L }
            .sum()
        val otherMs = if (firstPacketMs >= 0L) (firstPacketMs - knownMs).coerceAtLeast(0L) else -1L
        return buildString {
            append("frontend=").append(frontendMs).append("ms")
            append(",hidden=").append(hiddenMs).append("ms")
            append(",decoder=").append(decoderMs).append("ms")
            append(",vocoder=").append(vocoderMs).append("ms")
            append(",other=").append(otherMs).append("ms")
            append(",total=").append(firstPacketMs).append("ms")
        }
    }

    private fun formatModuleTiming(totalMs: Long, calls: Int): String {
        val avgMs = if (calls > 0) totalMs.toDouble() / calls else 0.0
        return "${totalMs}ms/${calls}x/${String.format(java.util.Locale.US, "%.1f", avgMs)}ms_avg"
    }

    private fun LitsTtsOrtRuntime.StreamingRuntimeMetrics.plus(
        other: LitsTtsOrtRuntime.StreamingRuntimeMetrics,
    ): LitsTtsOrtRuntime.StreamingRuntimeMetrics = LitsTtsOrtRuntime.StreamingRuntimeMetrics(
        hiddenEncoderMs = hiddenEncoderMs + other.hiddenEncoderMs,
        hiddenEncoderCalls = hiddenEncoderCalls + other.hiddenEncoderCalls,
        firstHiddenEncoderMs = if (firstHiddenEncoderMs >= 0L) firstHiddenEncoderMs else other.firstHiddenEncoderMs,
        decoderMs = decoderMs + other.decoderMs,
        decoderCalls = decoderCalls + other.decoderCalls,
        firstDecoderMs = if (firstDecoderMs >= 0L) firstDecoderMs else other.firstDecoderMs,
        vocoderMs = vocoderMs + other.vocoderMs,
        vocoderCalls = vocoderCalls + other.vocoderCalls,
        firstVocoderMs = if (firstVocoderMs >= 0L) firstVocoderMs else other.firstVocoderMs,
        firstChunkMs = if (firstChunkMs >= 0L) firstChunkMs else other.firstChunkMs,
        chunkCount = chunkCount + other.chunkCount,
        melLength = melLength + other.melLength,
        chunkSize = other.chunkSize,
        firstChunkSize = other.firstChunkSize,
        finalDecoderMode = other.finalDecoderMode,
    )

    private fun buildLoadProfile(
        layoutMs: Long,
        frontendMs: Long,
        runtimeMs: Long,
        runtimeProfile: String,
    ): String = buildString {
        append("layout=").append(layoutMs).append("ms")
        append(" frontendPreload=").append(frontendMs).append("ms")
        append(" ortCreate=").append(runtimeMs).append("ms")
        if (runtimeProfile.isNotBlank()) {
            append(" sessions=").append(runtimeProfile)
        }
    }

    private fun intExtraParam(value: Any?): Int? {
        return when (value) {
            is Number -> value.toInt()
            is String -> value.toIntOrNull()
            else -> null
        }?.takeIf { it > 0 }
    }

    private fun lengthScaleForSpeed(speed: Float): Float {
        val clampedSpeed = speed.takeIf { it.isFinite() }?.coerceIn(0.5f, 2.0f) ?: 1.0f
        return (1.0f / clampedSpeed).coerceIn(
            LitsTtsOrtRuntime.MIN_LENGTH_SCALE,
            LitsTtsOrtRuntime.MAX_LENGTH_SCALE,
        )
    }

}

internal fun streamingChunkSizeOverride(params: SpeakParams): Int? {
    params.streamingConfig?.chunkSize?.let { return it.takeIf { value -> value > 0 } }
    val value = params.extraParams["streamingChunkSize"] ?: params.extraParams["chunkSize"]
    return when (value) {
        is Number -> value.toInt()
        is String -> value.toIntOrNull()
        else -> null
    }?.takeIf { it > 0 }
}

internal fun streamingFirstChunkSizeOverride(params: SpeakParams): Int? {
    params.streamingConfig?.firstChunkSize?.let { return it.takeIf { value -> value > 0 } }
    val value = params.extraParams["streamingFirstChunkSize"] ?: params.extraParams["firstChunkSize"]
    return when (value) {
        is Number -> value.toInt()
        is String -> value.toIntOrNull()
        else -> null
    }?.takeIf { it > 0 }
}

private object AudioTransforms {
    fun apply(source: ShortArray, params: SpeakParams): ShortArray {
        var output = source
        if (params.pitch != 1.0f) {
            output = applyPitch(output, params.pitch.coerceIn(0.5f, 2.0f))
        }
        if (params.speed != 1.0f) {
            output = applySpeed(output, params.speed.coerceIn(0.5f, 2.0f))
        }
        if (params.volume != 1.0f) {
            output = applyVolume(output, params.volume.coerceIn(0.0f, 2.0f))
        }
        return output
    }

    fun applyPitchAndVolume(source: ShortArray, params: SpeakParams): ShortArray {
        var output = source
        if (params.pitch != 1.0f) {
            output = applyPitch(output, params.pitch.coerceIn(0.5f, 2.0f))
        }
        if (params.volume != 1.0f) {
            output = applyVolume(output, params.volume.coerceIn(0.0f, 2.0f))
        }
        return output
    }

    private fun applyPitch(input: ShortArray, pitch: Float): ShortArray {
        if (input.isEmpty()) return input
        val shifted = resampleToLength(input, (input.size / pitch).roundToInt().coerceAtLeast(1))
        return resampleToLength(shifted, input.size)
    }

    private fun applySpeed(input: ShortArray, speed: Float): ShortArray {
        if (input.isEmpty()) return input
        return resampleToLength(input, (input.size / speed).roundToInt().coerceAtLeast(1))
    }

    private fun applyVolume(input: ShortArray, volume: Float): ShortArray {
        val output = ShortArray(input.size)
        for (index in input.indices) {
            val scaled = (input[index] * volume).roundToInt().coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt())
            output[index] = scaled.toShort()
        }
        return output
    }

    private fun resampleToLength(input: ShortArray, targetLength: Int): ShortArray {
        if (input.isEmpty()) return input
        if (input.size == targetLength) return input.copyOf()
        if (targetLength <= 1) return shortArrayOf(input.first())
        val output = ShortArray(targetLength)
        val ratio = (input.size - 1).toDouble() / (targetLength - 1).toDouble()
        for (index in 0 until targetLength) {
            val position = index * ratio
            val left = position.toInt().coerceIn(0, input.lastIndex)
            val right = (left + 1).coerceAtMost(input.lastIndex)
            val fraction = position - left
            val value = input[left] + ((input[right] - input[left]) * fraction).roundToInt()
            output[index] = value.coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt()).toShort()
        }
        return output
    }
}

internal fun shortsToBytes(samples: ShortArray): ByteArray {
    val output = ByteArray(samples.size * 2)
    for (index in samples.indices) {
        val value = samples[index].toInt()
        output[index * 2] = (value and 0xff).toByte()
        output[index * 2 + 1] = ((value ushr 8) and 0xff).toByte()
    }
    return output
}

private fun elapsedMs(startedAt: Long): Long = (System.nanoTime() - startedAt) / 1_000_000L
