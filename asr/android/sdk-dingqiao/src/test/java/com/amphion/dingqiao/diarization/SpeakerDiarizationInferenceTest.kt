package com.amphion.dingqiao.diarization

import org.junit.Assert.assertArrayEquals
import org.junit.Test
import org.mockito.kotlin.mock

class SpeakerDiarizationInferenceTest {
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
