package com.amphion.asr.internal

import org.junit.Assert.assertEquals
import org.junit.Test

class NativeRule3DurationTest {
    @Test
    fun longModeDisableSentinelCannotBecomeImmediateNativeEndpoint() {
        assertEquals(Float.MAX_VALUE, NativeRule3Duration.forRecognizer(-1f), 0f)
    }

    @Test
    fun shortModeKeepsConfiguredNativeEndpointDuration() {
        assertEquals(60f, NativeRule3Duration.forRecognizer(60f), 0f)
    }
}
