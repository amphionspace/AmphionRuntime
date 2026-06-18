package com.lits.tts.sdk.internal

import android.content.Context
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
)

internal interface PcmSynthesizer {
    fun preload()

    fun synthesize(text: String, params: SpeakParams, engineParams: CreateEngineParams): SynthesizedAudio

    fun supportsInternalPlayback(): Boolean = true

    fun close() = Unit
}

internal class DeterministicPcmSynthesizer : PcmSynthesizer {
    override fun preload() = Unit

    override fun supportsInternalPlayback(): Boolean = false

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
        const val SAMPLE_RATE = 16000
    }
}

internal class LitsDeliveryPcmSynthesizer(
    private val context: Context,
    private val workPath: String?,
    private val speakerId: Int,
) : PcmSynthesizer {
    @Volatile
    private var layout: LitsTtsAssetInstaller.InstalledLayout? = null

    @Volatile
    private var runtime: LitsTtsOrtRuntime? = null

    override fun preload() {
        val activeLayout = ensureLayout()
        LitsTtsFrontend.preload(activeLayout)
        obtainRuntime(activeLayout)
    }

    override fun synthesize(text: String, params: SpeakParams, engineParams: CreateEngineParams): SynthesizedAudio {
        val startedAt = System.nanoTime()
        val activeLayout = layout ?: throw notReady()
        val activeRuntime = runtime ?: throw notReady()
        val tokenIds = LitsTtsFrontend.encode(activeLayout, text, engineParams.language, params.languageContext)
        val waveform = activeRuntime.synthesize(tokenIds, speakerId)
        val pcm = AudioTransforms.apply(LitsTtsOrtRuntime.floatToPcm16(waveform), params)
        return SynthesizedAudio(
            pcm = shortsToBytes(pcm),
            sampleRate = activeLayout.manifest.sampleRate,
            synthesisMs = (System.nanoTime() - startedAt) / 1_000_000L,
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
