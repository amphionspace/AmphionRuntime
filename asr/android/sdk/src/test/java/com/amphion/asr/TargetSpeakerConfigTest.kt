package com.amphion.asr

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TargetSpeakerConfigTest {
    @Test
    fun minimumSegmentDefaultsToZeroAndRequiresFiniteNonNegativeValues() {
        assertEquals(0f, TargetSpeakerConfig(modelPath = "/tmp/speaker.onnx").minSegSec)
        assertEquals(
            0f,
            TargetSpeakerConfig(modelPath = "/tmp/speaker.onnx", minSegSec = 0f).minSegSec,
        )
        assertTrue(
            runCatching {
                TargetSpeakerConfig(modelPath = "/tmp/speaker.onnx", minSegSec = -0.001f)
            }.isFailure,
        )
        assertTrue(
            runCatching {
                TargetSpeakerConfig(modelPath = "/tmp/speaker.onnx", minSegSec = Float.NaN)
            }.isFailure,
        )
        assertTrue(
            runCatching {
                TargetSpeakerConfig(
                    modelPath = "/tmp/speaker.onnx",
                    minSegSec = Float.POSITIVE_INFINITY,
                )
            }.isFailure,
        )
        assertTrue(
            runCatching {
                TargetSpeakerConfig(
                    modelPath = "/tmp/speaker.onnx",
                    minSegSec = Float.NEGATIVE_INFINITY,
                )
            }.isFailure,
        )
    }
}
