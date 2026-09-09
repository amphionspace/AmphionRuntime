package com.amphion.asr.internal

import java.security.KeyPairGenerator
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.util.Base64
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

    @Test
    fun `rotated second trust root accepts license signature`() {
        val generator = KeyPairGenerator.getInstance("EC").apply {
            initialize(ECGenParameterSpec("secp256r1"))
        }
        val oldKey = generator.generateKeyPair()
        val rotatedKey = generator.generateKeyPair()
        val payload = "enterprise-kms-interop".toByteArray()
        val signature = Signature.getInstance("SHA256withECDSA").run {
            initSign(rotatedKey.private)
            update(payload)
            sign()
        }
        val encoder = Base64.getEncoder()
        val trustSet = listOf(oldKey.public, rotatedKey.public)
            .joinToString(",") { encoder.encodeToString(it.encoded) }

        assertTrue(
            LicenseVerifier.verifyWithAnyTrustedKey(
                payload,
                signature,
                trustSet,
                Base64.getDecoder()::decode,
            ),
        )
    }
}
