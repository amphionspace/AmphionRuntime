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
        val shortConfirmed = selectSpeakerScoreSamples(
            strict,
            FloatArray(sampleRate / 2),
            minimum,
            asrSpeechConfirmed = true,
        )
        val emptyConfirmed = selectSpeakerScoreSamples(
            FloatArray(0),
            FloatArray(0),
            minimum,
            asrSpeechConfirmed = true,
        )
        val exactStrictWithoutAsr = selectSpeakerScoreSamples(
            FloatArray(minimum),
            FloatArray(0),
            minimum,
            asrSpeechConfirmed = false,
        )
        val exactStrictWithAsr = selectSpeakerScoreSamples(
            FloatArray(minimum),
            FloatArray(0),
            minimum,
            asrSpeechConfirmed = true,
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
        assertEquals(0, denied.samples.size)
        assertEquals(SpeakerScoreSource.UTTERANCE, shortConfirmed.source)
        assertEquals(sampleRate / 2, shortConfirmed.samples.size)
        assertEquals(SpeakerScoreSource.INSUFFICIENT, emptyConfirmed.source)
        assertEquals(SpeakerScoreSource.INSUFFICIENT, exactStrictWithoutAsr.source)
        assertEquals(SpeakerScoreSource.STRICT, exactStrictWithAsr.source)
        assertEquals(SpeakerScoreSource.STRICT, longStrict.source)
        assertEquals(minimum + sampleRate, longStrict.samples.size)
    }

    @Test
    fun zeroMinimumScoresTheWholeRealUtteranceInsteadOfAShortStrictFragment() {
        val strict = FloatArray(sampleRate / 10)
        val utterance = FloatArray(sampleRate / 2)

        val selected = selectSpeakerScoreSamples(
            strict,
            utterance,
            minSamples = 0,
            asrSpeechConfirmed = true,
        )

        assertEquals(SpeakerScoreSource.UTTERANCE, selected.source)
        assertTrue(selected.samples === utterance)
    }

    @Test
    fun sessionMinimumConversionPreservesZeroDuration() {
        assertEquals(0, speakerScoreMinimumSamples(minSegSec = 0f, sampleRate = sampleRate))
        assertEquals(
            sampleRate + sampleRate / 2,
            speakerScoreMinimumSamples(minSegSec = 1.5f, sampleRate = sampleRate),
        )
    }

    @Test
    fun scoreSelectionDiagnosticExplainsMissingScoreWithoutTextOrIdentity() {
        val selection = SpeakerScoreSelection(FloatArray(0), SpeakerScoreSource.INSUFFICIENT)

        val diagnostic = speakerScoreSelectionDiagnostic(
            selection,
            strictSampleCount = sampleRate,
            utteranceSampleCount = sampleRate + sampleRate / 4,
            minimumSampleCount = sampleRate + sampleRate / 2,
            sampleRate = sampleRate,
            asrSpeechConfirmed = false,
        )

        assertEquals(
            "voiceprint score selection: source=insufficient effectiveSpeechMs=1000 " +
                "utterancePcmMs=1250 minimumMs=1500 asrEvidence=false",
            diagnostic,
        )
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

    @Test
    fun speakerVadTailCopiesOnlyTheRequestedSuffixAcrossParts() {
        val buffers = SpeakerPcmBuffers(maxSamples = 100)
        buffers.observe(
            FloatArray(40) { it.toFloat() },
            captureSpeakerVad = true,
            captureFallback = false,
        )
        buffers.observe(
            FloatArray(40) { (40 + it).toFloat() },
            captureSpeakerVad = true,
            captureFallback = false,
        )

        assertArrayEquals(
            FloatArray(25) { (55 + it).toFloat() },
            buffers.speakerVadTail(25),
            0.0f,
        )
        assertEquals(0, buffers.speakerVadTail(0).size)
    }
}
