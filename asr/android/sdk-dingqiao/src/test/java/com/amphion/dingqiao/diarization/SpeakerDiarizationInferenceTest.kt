package com.amphion.dingqiao.diarization

import org.junit.Assert.assertArrayEquals
import org.junit.Test
import org.mockito.kotlin.mock

class SpeakerDiarizationInferenceTest {
    @Test
    fun queryRetainsUnclassifiedRealPcmButRequiresOneSecondOfConfirmedSpeech() {
        val inference = mock<SpeakerDiarizationInference>()
        val collect = SpeakerDiarizationInference::class.java.getDeclaredMethod(
            "collectQuerySamples", FloatArray::class.java, List::class.java, Int::class.javaPrimitiveType,
            Int::class.javaPrimitiveType, Int::class.javaPrimitiveType,
        ).also { it.isAccessible = true }
        val samples = FloatArray(64_000) { (it + 1) / 64_000f }
        val segments = mutableListOf(
            SpeakerSegmentationSegment(0, 16_000, 0, 1),
            SpeakerSegmentationSegment(20_000, 38_000, 0, 1),
            SpeakerSegmentationSegment(40_000, 42_000, 1, 2),
            SpeakerSegmentationSegment(44_000, 46_000, 0, 3),
            SpeakerSegmentationSegment(48_000, 64_000, 0, 1),
        )
        assertArrayEquals(
            samples.copyOfRange(16_000, 40_000) + samples.copyOfRange(42_000, 44_000) +
                samples.copyOfRange(46_000, 48_000),
            collect.invoke(inference, samples, segments, 0, 16_000, 48_000) as FloatArray, 0f,
        )
        segments[1] = SpeakerSegmentationSegment(20_000, 35_999, 0, 1)
        assertArrayEquals(floatArrayOf(),
            collect.invoke(inference, samples, segments, 0, 20_000, 48_000) as FloatArray, 0f)
        segments[1] = SpeakerSegmentationSegment(20_000, 36_000, 0, 1)
        assertArrayEquals(
            samples.copyOfRange(20_000, 40_000) + samples.copyOfRange(42_000, 44_000) +
                samples.copyOfRange(46_000, 48_000),
            collect.invoke(inference, samples, segments, 0, 20_000, 48_000) as FloatArray, 0f,
        )
        assertArrayEquals(floatArrayOf(),
            collect.invoke(inference, samples, segments, 0, 46_000, 48_000) as FloatArray, 0f)
    }

    @Test
    fun retainsLaterSpeechAndExcludesOverlapAndOtherSpeakers() {
        // Bypass native construction; invoke the production PCM selector itself.
        val inference = mock<SpeakerDiarizationInference>()
        val collect = SpeakerDiarizationInference::class.java.getDeclaredMethod(
            "collectSingleSpeakerSamples", FloatArray::class.java, List::class.java, Int::class.javaPrimitiveType,
            Int::class.javaPrimitiveType, Int::class.javaPrimitiveType,
        ).also { it.isAccessible = true }
        val samples = FloatArray(160_000) { it / 160_000f }
        val segments = listOf(
            SpeakerSegmentationSegment(0, 48_000, 0, 1),
            SpeakerSegmentationSegment(48_000, 64_000, 0, 3),
            SpeakerSegmentationSegment(64_000, 96_000, 1, 2),
            SpeakerSegmentationSegment(96_000, 144_000, 0, 1),
        )
        assertArrayEquals(
            samples.copyOfRange(0, 48_000) + samples.copyOfRange(96_000, 144_000),
            collect.invoke(inference, samples, segments, 0, 0, samples.size) as FloatArray, 0f,
        )
        assertArrayEquals(samples.copyOfRange(64_000, 96_000),
            collect.invoke(inference, samples, segments, 1, 0, samples.size) as FloatArray, 0f)
        assertArrayEquals(floatArrayOf(), collect.invoke(inference, samples, segments, 2, 0, samples.size) as FloatArray, 0f)
        assertArrayEquals(samples.copyOfRange(96_000, 128_000),
            collect.invoke(inference, samples, segments, 0, 96_000, 128_000) as FloatArray, 0f)
        assertArrayEquals(floatArrayOf(),
            collect.invoke(inference, samples, segments, 1, 96_000, 128_000) as FloatArray, 0f)
    }
}
