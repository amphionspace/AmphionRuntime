package com.amphion.asr.internal

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LicenseVerifierTest {

    @Test
    fun `zero major is unbounded`() {
        assertTrue(LicenseVerifier.sdkMajorMatches(licensedMajor = 0, runtimeMajor = 1))
    }

    @Test
    fun `positive major must match`() {
        assertTrue(LicenseVerifier.sdkMajorMatches(licensedMajor = 1, runtimeMajor = 1))
        assertFalse(LicenseVerifier.sdkMajorMatches(licensedMajor = 2, runtimeMajor = 1))
    }

    @Test
    fun `missing major keeps legacy compatibility`() {
        assertTrue(LicenseVerifier.sdkMajorMatches(licensedMajor = -1, runtimeMajor = 1))
    }
}
