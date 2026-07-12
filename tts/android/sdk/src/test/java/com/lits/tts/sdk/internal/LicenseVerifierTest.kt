package com.lits.tts.sdk.internal

import com.lits.tts.sdk.TtsErrorCode
import com.lits.tts.sdk.TtsLicenseStatus
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.text.SimpleDateFormat
import java.util.Base64
import java.util.Locale
import java.util.TimeZone
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LicenseVerifierTest {

    private val appId = "com.lits.tts.demo"
    private val keyPair: KeyPair = newKeyPair()
    private val publicKeyB64: String = Base64.getEncoder().encodeToString(keyPair.public.encoded)

    @Test
    fun emptyPublicKeyIsDevUnlicensed() {
        val r = LicenseVerifier.verifyResolved(
            licenseText = null,
            publicKeyB64 = "",
            packageName = appId,
            hostCertSha256 = emptySet(),
            deviceSerial = null,
            expiryGraceDays = 0,
            sdkMajor = 1,
            sdkReleaseDate = "2026-06-01",
            requiredFeature = "TTS",
            nowMillis = utc("2026-06-01"),
        )
        assertTrue(r.ok)
        assertEquals(TtsLicenseStatus.State.DEV_UNLICENSED, r.status.state)
        assertFalse(r.status.valid)
    }

    @Test
    fun armedButMissingLicenseFails() {
        val r = verify(licenseText = null)
        assertFalse(r.ok)
        assertEquals(TtsErrorCode.LICENSE_MISSING, r.errorCode)
        assertEquals(TtsLicenseStatus.State.INVALID, r.status.state)
    }

    @Test
    fun validAppOnlyLicenseIsLicensed() {
        val lic = issue(claims(applicationId = appId, expiresAt = "2027-01-01", customer = "ACME Co."))
        val r = verify(licenseText = lic)
        assertTrue(r.errorMessage, r.ok)
        assertEquals(TtsLicenseStatus.State.LICENSED, r.status.state)
        assertTrue(r.status.valid)
        assertEquals("ACME Co.", r.status.customer)
        assertEquals(appId, r.status.applicationId)
    }

    @Test
    fun applicationIdMismatchFails() {
        val lic = issue(claims(applicationId = "com.other.app"))
        val r = verify(licenseText = lic)
        assertEquals(TtsErrorCode.LICENSE_APP_MISMATCH, r.errorCode)
    }

    @Test
    fun tamperedSignatureFails() {
        val attacker = newKeyPair()
        val payloadBytes = claims(applicationId = appId).toByteArray(Charsets.UTF_8)
        val sig = sign(attacker, payloadBytes)
        val lic = envelope(payloadBytes, sig)
        val r = verify(licenseText = lic)
        assertEquals(TtsErrorCode.LICENSE_SIGNATURE_INVALID, r.errorCode)
    }

    @Test
    fun malformedEnvelopeFails() {
        val r = verify(licenseText = "{ not a valid envelope }")
        assertEquals(TtsErrorCode.LICENSE_MALFORMED, r.errorCode)
    }

    @Test
    fun expiredLicenseFails() {
        val lic = issue(claims(applicationId = appId, expiresAt = "2026-01-01"))
        val r = verify(licenseText = lic, nowMillis = utc("2026-06-01"))
        assertEquals(TtsErrorCode.LICENSE_EXPIRED, r.errorCode)
    }

    @Test
    fun expiryGraceKeepsLicenseValid() {
        val lic = issue(claims(applicationId = appId, expiresAt = "2026-01-01"))
        val r = LicenseVerifier.verifyResolved(
            licenseText = lic,
            publicKeyB64 = publicKeyB64,
            packageName = appId,
            hostCertSha256 = emptySet(),
            deviceSerial = null,
            expiryGraceDays = 5,
            sdkMajor = 1,
            sdkReleaseDate = "2026-06-01",
            requiredFeature = "TTS",
            nowMillis = utc("2026-01-05"),
        )
        assertTrue(r.ok)
        assertEquals(TtsLicenseStatus.State.LICENSED, r.status.state)
    }

    @Test
    fun certBindingMatchesAndMismatches() {
        val cert = "AABBCCDDEEFF00112233445566778899AABBCCDDEEFF00112233445566778899"
        val lic = issue(claims(applicationId = appId, certSha256 = cert))

        val ok = verifyWith(lic, hostCert = setOf(cert))
        assertTrue(ok.ok)
        assertEquals(TtsLicenseStatus.State.LICENSED, ok.status.state)

        val bad = verifyWith(lic, hostCert = setOf("DEADBEEF"))
        assertEquals(TtsErrorCode.LICENSE_CERT_MISMATCH, bad.errorCode)
    }

    @Test
    fun snWhitelistMatchesAndMismatches() {
        val saltId = "DQ-TIASSISTANT-20260623-69CD375699165832C1D2E9EA77C8BE71"
        val serial = "SN-001"
        val hash = DeviceLicenseFingerprint.computeFromSerial(serial, saltId)
        val lic = issue(claims(applicationId = appId, deviceIdSaltId = saltId, authorizedDeviceHashes = listOf(hash)))

        val ok = verifyWith(lic, deviceSerial = serial.lowercase(Locale.ROOT))
        assertTrue(ok.ok)

        val bad = verifyWith(lic, deviceSerial = "SN-999")
        assertEquals(TtsErrorCode.LICENSE_DEVICE_MISMATCH, bad.errorCode)
    }

    @Test
    fun legacyDeviceHashStillMatchesOverride() {
        val device = "0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF"
        val lic = issue(claims(applicationId = appId, deviceSha256 = device))

        val ok = verifyWith(lic, hostDeviceSha256 = device)
        assertTrue(ok.ok)

        val bad = verifyWith(lic, hostDeviceSha256 = "FEDCBA9876543210")
        assertEquals(TtsErrorCode.LICENSE_DEVICE_MISMATCH, bad.errorCode)
    }

    @Test
    fun sdkMajorMismatchFails() {
        val lic = issue(claims(applicationId = appId, sdkMajor = 2))
        val r = verifyWith(lic, sdkMajor = 1)
        assertEquals(TtsErrorCode.LICENSE_SDK_MAJOR_MISMATCH, r.errorCode)
    }

    @Test
    fun maintenanceWindowRejectsNewerSdkRelease() {
        val lic = issue(claims(applicationId = appId, maintenanceUntil = "2026-01-31"))
        val r = verifyWith(lic, sdkReleaseDate = "2026-02-01")
        assertEquals(TtsErrorCode.LICENSE_MAINTENANCE_EXPIRED, r.errorCode)
    }

    @Test
    fun missingTtsFeatureFails() {
        val lic = issue(claims(applicationId = appId, features = listOf("ASR")))
        val r = verifyWith(lic)
        assertEquals(TtsErrorCode.LICENSE_FEATURE_MISSING, r.errorCode)
    }

    /**
     * 鼎桥离线 license 交付形态：applicationId / bundleName 均为空（packageNameBound=false），
     * 改用 cert + SN 白名单绑定。武装态下必须按 LICENSED 通过，不能误判 LICENSE_APP_MISMATCH。
     * 锁定 LicenseVerifier 的空包名放行（app-binding guard）。
     */
    @Test
    fun blankApplicationIdIsNotAppBound() {
        val cert = "AABBCCDDEEFF00112233445566778899AABBCCDDEEFF00112233445566778899"
        val saltId = "DQ-TIASSISTANT-20260623-69CD375699165832C1D2E9EA77C8BE71"
        val serial = "SN-001"
        val hash = DeviceLicenseFingerprint.computeFromSerial(serial, saltId)
        val lic = issue(
            claims(
                applicationId = "",
                certSha256 = cert,
                deviceIdSaltId = saltId,
                authorizedDeviceHashes = listOf(hash),
                features = listOf("TTS"),
            ),
        )
        val r = verifyWith(lic, hostCert = setOf(cert), deviceSerial = serial)
        assertTrue(r.errorMessage, r.ok)
        assertEquals(TtsLicenseStatus.State.LICENSED, r.status.state)
    }

    /** 空 features 授权不到任何能力，必须拒绝激活 TTS（与 ASR 验签器一致，堵住能力门禁绕过）。 */
    @Test
    fun emptyFeaturesDeniesTts() {
        val lic = issue(claims(applicationId = appId, features = emptyList()))
        val r = verifyWith(lic)
        assertEquals(TtsErrorCode.LICENSE_FEATURE_MISSING, r.errorCode)
    }

    /** 鼎桥能力分档诉求：requiredFeature=TTS 下 asr-only 拒绝、tts-only 与 asr&tts 放行。 */
    @Test
    fun featureTierMatrixForTts() {
        assertEquals(
            TtsErrorCode.LICENSE_FEATURE_MISSING,
            verifyWith(issue(claims(applicationId = appId, features = listOf("ASR")))).errorCode,
        )
        assertTrue(verifyWith(issue(claims(applicationId = appId, features = listOf("TTS")))).ok)
        assertTrue(verifyWith(issue(claims(applicationId = appId, features = listOf("ASR", "TTS")))).ok)
    }

    private fun verify(licenseText: String?, nowMillis: Long = utc("2026-06-01")) =
        LicenseVerifier.verifyResolved(
            licenseText = licenseText,
            publicKeyB64 = publicKeyB64,
            packageName = appId,
            hostCertSha256 = emptySet(),
            deviceSerial = null,
            expiryGraceDays = 0,
            sdkMajor = 1,
            sdkReleaseDate = "2026-06-01",
            requiredFeature = "TTS",
            nowMillis = nowMillis,
        )

    private fun verifyWith(
        licenseText: String,
        hostCert: Set<String> = emptySet(),
        deviceSerial: String? = null,
        hostDeviceSha256: String? = null,
        sdkMajor: Int = 1,
        sdkReleaseDate: String = "2026-06-01",
    ) = LicenseVerifier.verifyResolved(
        licenseText = licenseText,
        publicKeyB64 = publicKeyB64,
        packageName = appId,
        hostCertSha256 = hostCert,
        deviceSerial = deviceSerial,
        hostDeviceSha256 = hostDeviceSha256,
        expiryGraceDays = 0,
        sdkMajor = sdkMajor,
        sdkReleaseDate = sdkReleaseDate,
        requiredFeature = "TTS",
        nowMillis = utc("2026-06-01"),
    )

    private fun issue(claimsJson: String): String {
        val payloadBytes = claimsJson.toByteArray(Charsets.UTF_8)
        return envelope(payloadBytes, sign(keyPair, payloadBytes))
    }

    private fun envelope(payloadBytes: ByteArray, sig: ByteArray): String {
        val enc = Base64.getEncoder()
        return JSONObject()
            .put("payload_b64", enc.encodeToString(payloadBytes))
            .put("alg", "SHA256withECDSA")
            .put("sig_b64", enc.encodeToString(sig))
            .toString()
    }

    private fun claims(
        applicationId: String,
        expiresAt: String = "",
        certSha256: String = "",
        deviceIdSaltId: String = "",
        authorizedDeviceHashes: List<String> = emptyList(),
        deviceSha256: String = "",
        customer: String = "ACME",
        licenseId: String = "LIC-1",
        sdkMajor: Int = 1,
        maintenanceUntil: String = "2026-12-31",
        features: List<String> = listOf("TTS"),
    ): String = JSONObject()
        .put("applicationId", applicationId)
        .put("bundleName", applicationId)
        .put("certSha256", certSha256)
        .put("signingCertDigest", certSha256)
        .put("deviceIdHashAlg", "SHA-256")
        .put("deviceIdSaltId", deviceIdSaltId)
        .put("authorizedDeviceHashes", JSONArray(authorizedDeviceHashes))
        .put("deviceSha256", deviceSha256)
        .put("customer", customer)
        .put("licenseId", licenseId)
        .put("issuedAt", "2026-01-01")
        .put("expiresAt", expiresAt)
        .put("maintenanceUntil", maintenanceUntil)
        .put("installTier", "LE_100K")
        .put("features", JSONArray(features))
        .put("sdkMajor", sdkMajor)
        .toString()

    private fun sign(kp: KeyPair, bytes: ByteArray): ByteArray =
        Signature.getInstance("SHA256withECDSA").run {
            initSign(kp.private)
            update(bytes)
            sign()
        }

    private fun newKeyPair(): KeyPair = KeyPairGenerator.getInstance("EC").run {
        initialize(ECGenParameterSpec("secp256r1"))
        generateKeyPair()
    }

    private fun utc(date: String): Long =
        SimpleDateFormat("yyyy-MM-dd", Locale.ROOT).apply {
            timeZone = TimeZone.getTimeZone("UTC")
        }.parse(date)!!.time
}
