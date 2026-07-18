package com.amphion.asr.internal

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.sin

class EffectiveSpeechBufferTest {
    private val sampleRate = 16_000

    @Test
    fun vadEvidenceRetainsLowVolumeSpeechWithoutLeadingContext() {
        val buffer = EffectiveSpeechBuffer(sampleRate, 25 * sampleRate)
        val leading = FloatArray(sampleRate / 4)
        val speech = constantEnvelope((1.5 * sampleRate).toInt(), 0.002f)
        val trailing = FloatArray(sampleRate / 4)

        buffer.observe(leading)
        buffer.observe(speech)
        buffer.confirmSpeech()
        buffer.observe(trailing)

        assertArrayEquals(speech, buffer.take(), 0.0f)
    }

    @Test
    fun steadyHighEnergyToneIsRejectedWithoutVadOrAsrEvidence() {
        val buffer = EffectiveSpeechBuffer(sampleRate, 25 * sampleRate)
        val tone = FloatArray(2 * sampleRate) { index ->
            (sin(2.0 * Math.PI * 100.0 * index / sampleRate) * 0.04).toFloat()
        }

        buffer.observe(tone)

        assertEquals(0, buffer.take().size)
    }

    @Test
    fun acousticSpeechDecisionDoesNotDependOnCallerChunking() {
        val signal = varyingSpeechLike(2 * sampleRate)
        val merged = EffectiveSpeechBuffer(sampleRate, 25 * sampleRate)
        val framed = EffectiveSpeechBuffer(sampleRate, 25 * sampleRate)

        merged.observe(signal)
        var offset = 0
        while (offset < signal.size) {
            val size = minOf(signal.size - offset, offset % 997 + 1)
            framed.observe(signal.copyOfRange(offset, offset + size))
            offset += size
        }

        assertArrayEquals(merged.take(), framed.take(), 0.0f)
    }

    @Test
    fun tokenOnlyEndpointKeepsAudioForTheNextPublicFinal() {
        val buffer = EffectiveSpeechBuffer(sampleRate, 25 * sampleRate)
        buffer.observe(constantEnvelope(sampleRate, 0.002f))

        val tokenOnly = buffer.resolveFinal(publicText = "", asrSpeechConfirmed = true, isLast = false)
        assertFalse(tokenOnly.publish)
        assertEquals(0, tokenOnly.samples.size)

        buffer.observe(FloatArray(sampleRate / 50))
        buffer.observe(constantEnvelope(sampleRate / 2, 0.002f))
        val publicFinal = buffer.resolveFinal(
            publicText = "recognized",
            asrSpeechConfirmed = true,
            isLast = false,
        )

        assertTrue(publicFinal.publish)
        assertEquals((1.5 * sampleRate).toInt(), publicFinal.samples.size)
    }

    @Test
    fun shortStrictSpeechFallsBackOnlyToRealUtterancePcmWithAsrEvidence() {
        val strict = FloatArray(sampleRate)
        val utterance = FloatArray((1.5 * sampleRate).toInt())
        val minimum = utterance.size

        val fallback = selectSpeakerScoreSamples(strict, utterance, minimum, asrSpeechConfirmed = true)
        val denied = selectSpeakerScoreSamples(strict, utterance, minimum, asrSpeechConfirmed = false)
        val stillShort = selectSpeakerScoreSamples(
            strict,
            FloatArray(minimum - 1),
            minimum,
            asrSpeechConfirmed = true,
        )
        val exactStrict = selectSpeakerScoreSamples(
            FloatArray(minimum),
            FloatArray(0),
            minimum,
            asrSpeechConfirmed = false,
        )
        val longStrict = selectSpeakerScoreSamples(
            FloatArray(minimum + sampleRate),
            FloatArray(minimum + 2 * sampleRate),
            minimum,
            asrSpeechConfirmed = true,
        )

        assertEquals(SpeakerScoreSource.UTTERANCE, fallback.source)
        assertEquals(utterance.size, fallback.samples.size)
        assertEquals(SpeakerScoreSource.INSUFFICIENT, denied.source)
        assertEquals(strict.size, denied.samples.size)
        assertEquals(SpeakerScoreSource.INSUFFICIENT, stillShort.source)
        assertEquals(SpeakerScoreSource.STRICT, exactStrict.source)
        assertEquals(SpeakerScoreSource.STRICT, longStrict.source)
        assertEquals(minimum + sampleRate, longStrict.samples.size)
    }

    private fun constantEnvelope(size: Int, level: Float): FloatArray =
        FloatArray(size) { index -> if (index % 16 < 8) level else -level }

    private fun varyingSpeechLike(size: Int): FloatArray {
        val windowSamples = sampleRate / 50
        val levels = floatArrayOf(0.02f, 0.08f, 0.03f, 0.12f)
        return FloatArray(size) { index ->
            val level = levels[(index / windowSamples) % levels.size]
            if (index % 16 < 8) level else -level
        }
    }
}

class RecognizerResetGenerationTest {
    @Test
    fun endpointInsideChunkInvalidatesTheOldVadDecision() {
        val generation = RecognizerResetGeneration()
        val beforeDecode = generation.snapshot()

        generation.markReset()

        assertTrue(generation.changedSince(beforeDecode))
    }

    @Test
    fun ordinaryPartialKeepsTheCurrentVadDecision() {
        val generation = RecognizerResetGeneration()
        val beforeDecode = generation.snapshot()

        assertFalse(generation.changedSince(beforeDecode))
    }
}

class SpeakerPcmBuffersTest {
    @Test
    fun nativeSegmentResetDoesNotDiscardPublicUtteranceFallback() {
        val buffers = SpeakerPcmBuffers(maxSamples = 100)
        val first = FloatArray(40) { 1.0f }
        val second = FloatArray(30) { 2.0f }

        buffers.observe(first, captureSpeakerVad = true, captureFallback = true)
        buffers.clearNativeSegment()
        buffers.observe(second, captureSpeakerVad = true, captureFallback = true)

        assertEquals(30, buffers.speakerVadLength())
        assertEquals(70, buffers.fallbackSamples().size)
    }

    @Test
    fun buffersEnforceIndependentCaps() {
        val buffers = SpeakerPcmBuffers(maxSamples = 50)

        buffers.observe(FloatArray(80), captureSpeakerVad = true, captureFallback = false)
        buffers.observe(FloatArray(80), captureSpeakerVad = false, captureFallback = true)

        assertEquals(50, buffers.speakerVadLength())
        assertEquals(50, buffers.fallbackSamples().size)
    }
}
