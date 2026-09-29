package com.lits.tts.sdk.internal

import android.content.Context
import android.content.ContextWrapper
import android.util.Base64
import androidx.test.platform.app.InstrumentationRegistry
import com.lits.tts.sdk.TtsErrorCode
import java.security.KeyPairGenerator
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test

/** Real Android JSON, ECDSA and host-package checks; the ephemeral key never changes SDK trust. */
class LicensePackagePolicyDeviceTest {
    private val host = InstrumentationRegistry.getInstrumentation().targetContext
    private val keys = KeyPairGenerator.getInstance("EC").apply {
        initialize(ECGenParameterSpec("secp256r1"))
    }.generateKeyPair()
    private fun b64(bytes: ByteArray) = Base64.encodeToString(bytes, Base64.NO_WRAP)
    private fun claims(mode: String?) = JSONObject().apply {
        put("features", JSONArray().put("TTS"))
        put("applicationId", "example.primary")
        if (mode != null) put("applicationBindingMode", mode)
    }
    private fun signed(payload: JSONObject): String {
        val bytes = payload.toString().toByteArray(Charsets.UTF_8)
        val signature = Signature.getInstance("SHA256withECDSA").run {
            initSign(keys.private); update(bytes); sign()
        }
        return JSONObject().put("payload_b64", b64(bytes))
            .put("sig_b64", b64(signature)).put("alg", "SHA256withECDSA").toString()
    }
    private fun verify(payload: JSONObject, context: Context = host): Int = LicenseVerifier.verify(
        ctx = context, licenseText = signed(payload), publicKeyB64 = b64(keys.public.encoded),
        expiryGraceDays = 0,
    ).errorCode

    @Test fun allowlistAcceptsBothEntriesAndRejectsOtherHost() {
        val payload = claims("allowlist").put("applicationIds",
            JSONArray().put("example.primary").put(host.packageName))
        assertEquals(TtsErrorCode.OK, verify(payload))
        val primary = object : ContextWrapper(host) {
            override fun getPackageName() = "example.primary"
        }
        assertEquals(TtsErrorCode.OK, verify(payload, primary))
        payload.put("applicationIds", JSONArray().put("example.primary").put("example.secondary"))
        assertEquals(TtsErrorCode.LICENSE_APP_MISMATCH, verify(payload))
    }
    @Test fun noneAndRecordOnlyAllowUnlistedHost() {
        for (mode in listOf("none", "record-only")) assertEquals(TtsErrorCode.OK, verify(claims(mode)))
    }
    @Test fun boundRequiresMatchingHost() {
        assertEquals(TtsErrorCode.LICENSE_APP_MISMATCH, verify(claims("bound")))
        assertEquals(TtsErrorCode.OK, verify(claims("bound").put("applicationId", host.packageName)))
    }
    @Test fun legacyPolicyPreservesPlatformContract() {
        assertEquals(TtsErrorCode.LICENSE_APP_MISMATCH, verify(claims(null)))
        assertEquals(TtsErrorCode.OK, verify(claims(null).put("applicationId", host.packageName)))
    }
    @Test fun unknownAndEmptyAllowlistFailClosed() {
        assertEquals(TtsErrorCode.LICENSE_APP_MISMATCH, verify(claims("unknown")))
        assertEquals(TtsErrorCode.LICENSE_APP_MISMATCH, verify(claims("allowlist")))
    }
    @Test fun unavailableHostCertificateCannotSatisfyBinding() {
        val missing = object : ContextWrapper(host) {
            override fun getPackageName() = "example.package.does.not.exist"
        }
        assertEquals(TtsErrorCode.LICENSE_CERT_MISMATCH,
            verify(claims("none").put("signingCertDigest", "01".repeat(32)), missing))
    }
    @Test fun editingSignedPolicyIsRejected() {
        val envelope = JSONObject(signed(claims("allowlist")))
        envelope.put("payload_b64", b64(claims("none").toString().toByteArray(Charsets.UTF_8)))
        assertEquals(TtsErrorCode.LICENSE_SIGNATURE_INVALID, LicenseVerifier.verify(
            ctx = host, licenseText = envelope.toString(), publicKeyB64 = b64(keys.public.encoded),
            expiryGraceDays = 0,
        ).errorCode)
    }
}
