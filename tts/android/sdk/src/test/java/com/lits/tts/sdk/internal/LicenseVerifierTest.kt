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

/**
 * [LicenseVerifier.verifyResolved] 纯逻辑测试：用运行时生成的 ECDSA P-256 密钥对真实签发 /
 * 验签，覆盖 DEV / 正常 / 各类绑定失败 / 过期。无需 Android Context（验签核心不依赖平台）。
 */
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
            hostDeviceSha256 = "",
            expiryGraceDays = 0,
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
        // 用另一把私钥签名，但用本测试的公钥验签 → 签名不匹配。
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
        // 到期次日 + 5 天宽限 → deadline = 2026-01-07，2026-01-05 仍有效。
        val r = LicenseVerifier.verifyResolved(
            licenseText = lic,
            publicKeyB64 = publicKeyB64,
            packageName = appId,
            hostCertSha256 = emptySet(),
            hostDeviceSha256 = "",
            expiryGraceDays = 5,
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
    fun deviceBindingMatchesAndMismatches() {
        val device = "0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF"
        val lic = issue(claims(applicationId = appId, deviceSha256 = device))

        val ok = verifyWith(lic, hostDevice = device)
        assertTrue(ok.ok)

        val bad = verifyWith(lic, hostDevice = "FEDCBA9876543210")
        assertEquals(TtsErrorCode.LICENSE_DEVICE_MISMATCH, bad.errorCode)
    }

    // -------- helpers --------

    private fun verify(licenseText: String?, nowMillis: Long = utc("2026-06-01")) =
        LicenseVerifier.verifyResolved(
            licenseText = licenseText,
            publicKeyB64 = publicKeyB64,
            packageName = appId,
            hostCertSha256 = emptySet(),
            hostDeviceSha256 = "",
            expiryGraceDays = 0,
            nowMillis = nowMillis,
        )

    private fun verifyWith(
        licenseText: String,
        hostCert: Set<String> = emptySet(),
        hostDevice: String = "",
    ) = LicenseVerifier.verifyResolved(
        licenseText = licenseText,
        publicKeyB64 = publicKeyB64,
        packageName = appId,
        hostCertSha256 = hostCert,
        hostDeviceSha256 = hostDevice,
        expiryGraceDays = 0,
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
        deviceSha256: String = "",
        customer: String = "ACME",
        licenseId: String = "LIC-1",
    ): String = JSONObject()
        .put("applicationId", applicationId)
        .put("certSha256", certSha256)
        .put("deviceSha256", deviceSha256)
        .put("customer", customer)
        .put("licenseId", licenseId)
        .put("issuedAt", "2026-01-01")
        .put("expiresAt", expiresAt)
        .put("installTier", "LE_100K")
        .put("features", JSONArray(listOf("TTS_ZH_EN")))
        .put("sdkMajor", 0)
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
