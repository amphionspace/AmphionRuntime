package com.amphion.asr.internal

import java.security.KeyFactory
import java.security.Signature
import java.security.spec.PKCS8EncodedKeySpec
import java.security.KeyPairGenerator
import java.security.spec.ECGenParameterSpec
import java.util.Base64
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 与 Python 签发端互测：fixtures.json 由 tools/license/quota/gen_sdk_fixtures.py 生成，
 * 期望错误码由 Python verify_chain 得出。两端每条结果必须一致。
 */
class QuotaChainVerifierTest {

    private val b64: (String) -> ByteArray = { Base64.getDecoder().decode(it) }

    private class SoftKey(pkcs8: ByteArray, private val spki: ByteArray) : QuotaChainVerifier.DeviceKey {
        private val priv = KeyFactory.getInstance("EC").generatePrivate(PKCS8EncodedKeySpec(pkcs8))
        override fun publicKeySpki(): ByteArray = spki
        override fun sign(challenge: ByteArray): ByteArray =
            Signature.getInstance("SHA256withECDSA").run { initSign(priv); update(challenge); sign() }
    }

    @Suppress("UNCHECKED_CAST")
    @Test
    fun `python issued fixtures verify identically on JVM`() {
        val text = javaClass.classLoader!!.getResource("quota-chain/fixtures.json")!!.readText(Charsets.UTF_8)
        val doc = StrictJson.parse(text) as Map<String, Any?>
        val roots = doc["trustedRoots"] as String
        val cases = doc["cases"] as List<Map<String, Any?>>
        assertTrue(cases.size >= 15)
        val mismatches = mutableListOf<String>()
        for (c in cases) {
            val ctx = QuotaChainVerifier.Context(
                serial = c["serial"] as String, bundleName = c["bundle"] as String,
                sdkMajor = (c["sdkMajor"] as Long).toInt(), sdkReleaseDate = c["sdkReleaseDate"] as String,
                requiredFeature = c["feature"] as String, today = c["today"] as String,
                deviceKey = SoftKey(b64(c["deviceKeyPkcs8"] as String), b64(c["deviceKeySpki"] as String)),
            )
            val got = try {
                val r = QuotaChainVerifier.verify(c["license"] as String, roots, ctx, b64)
                if (c["expectSeq"] != null) assertEquals(c["name"] as String, c["expectSeq"], r.seq)
                "OK"
            } catch (e: QuotaChainVerifier.ChainException) { e.code }
            if (got != c["expect"]) mismatches += "${c["name"]}: python=${c["expect"]} jvm=$got"
        }
        assertEquals(mismatches.joinToString("\n"), 0, mismatches.size)
    }

    @Test
    fun `unarmed sdk refuses chain`() {
        val ctx = QuotaChainVerifier.Context("SN0001", "", 1, "", "ASR", "2026-11-27", newSoftKey())
        val code = try { QuotaChainVerifier.verify("{}", "", ctx, b64); "OK" } catch (e: QuotaChainVerifier.ChainException) { e.code }
        assertEquals("NOT_ARMED", code)
    }

    @Test
    fun `strict json rejects ambiguity`() {
        for (bad in listOf("""{"a":1,"a":2}""", """{"a":1.5}""", """{"a":NaN}""", """{"a":1} x""", """{"a":01}""")) {
            val rejected = try { StrictJson.parse(bad); false } catch (_: StrictJson.JsonError) { true }
            assertTrue(bad, rejected)
        }
        assertEquals(mapOf("k" to listOf(1L, "中文\n")), StrictJson.parse("""{"k":[1,"中文\n"]}"""))
    }

    @Test
    fun `isChain distinguishes formats`() {
        assertTrue(QuotaChainVerifier.isChain("""{"format":"amphion.quota-chain.v1"}"""))
        assertFalse(QuotaChainVerifier.isChain("""{"payload_b64":"x","sig_b64":"y","alg":"SHA256withECDSA"}"""))
    }

    private class MemClock(var day: String) : LicenseClock {
        override fun read(): String = day
        override fun write(day: String) { this.day = day }
    }

    @Suppress("UNCHECKED_CAST")
    private fun fixture(name: String): Pair<String, Map<String, Any?>> {
        val text = javaClass.classLoader!!.getResource("quota-chain/fixtures.json")!!.readText(Charsets.UTF_8)
        val doc = StrictJson.parse(text) as Map<String, Any?>
        return doc["trustedRoots"] as String to (doc["cases"] as List<Map<String, Any?>>).first { it["name"] == name }
    }

    private fun millis(day: String): Long =
        java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.ROOT)
            .apply { timeZone = java.util.TimeZone.getTimeZone("UTC") }.parse(day)!!.time

    private fun dispatch(name: String, now: String, clock: LicenseClock): LicenseVerifier.Result {
        val (roots, c) = fixture(name)
        return LicenseVerifier.verifyQuotaChain(
            c["license"] as String, roots, c["bundle"] as String, c["serial"] as String,
            (c["sdkMajor"] as Long).toInt(), c["sdkReleaseDate"] as String, c["feature"] as String, millis(now),
            SoftKey(b64(c["deviceKeyPkcs8"] as String), b64(c["deviceKeySpki"] as String)), clock, b64,
        )
    }

    @Test
    fun `sdk dispatch maps chain result to license status and advances clock watermark`() {
        val (_, c) = fixture("ok_seq1")
        val clock = MemClock("")
        val r = dispatch("ok_seq1", c["today"] as String, clock)
        assertTrue(r.errorMessage, r.ok)
        assertEquals("quota", r.status.installTier)
        assertTrue(r.status.licenseId.endsWith("#1"))
        assertEquals(c["today"], clock.day)
        val wrongKey = LicenseVerifier.verifyQuotaChain(c["license"] as String, fixture("ok_seq1").first,
            c["bundle"] as String, c["serial"] as String, 1, c["sdkReleaseDate"] as String, "ASR",
            millis(c["today"] as String), newSoftKey(), MemClock(""), b64)
        assertEquals(com.amphion.asr.AsrErrorCode.LICENSE_DEVICE_MISMATCH, wrongKey.errorCode)
    }

    @Test
    fun `rolled back device clock cannot revive an expired license`() {
        val (_, c) = fixture("expired")
        val r = dispatch("expired", "2020-01-01", MemClock(c["today"] as String))
        assertEquals(com.amphion.asr.AsrErrorCode.LICENSE_EXPIRED, r.errorCode)
    }

    @Test
    fun `missing device key fails closed`() {
        val (roots, c) = fixture("ok_seq1")
        val gone = object : QuotaChainVerifier.DeviceKey {
            override fun publicKeySpki(): ByteArray = throw IllegalStateException("gone")
            override fun sign(challenge: ByteArray): ByteArray = throw IllegalStateException("gone")
        }
        val r = LicenseVerifier.verifyQuotaChain(c["license"] as String, roots, c["bundle"] as String,
            c["serial"] as String, 1, "", "ASR", millis(c["today"] as String), gone, MemClock(""), b64)
        assertEquals(com.amphion.asr.AsrErrorCode.LICENSE_DEVICE_MISMATCH, r.errorCode)
    }

    @Suppress("UNCHECKED_CAST")
    @Test
    fun `activation request and receipt are signed by the device key`() {
        val (_, c) = fixture("ok_seq1")
        val key = SoftKey(b64(c["deviceKeyPkcs8"] as String), b64(c["deviceKeySpki"] as String))
        val enc: (ByteArray) -> String = { Base64.getEncoder().encodeToString(it) }
        val req = QuotaChainVerifier.activationRequest(" sn0000abcd ", "DQ-TEST-QUOTA-SALT-0001", "android_arm64",
            "com.dingqiao.police", "2026-11-27", key, enc)
        val receipt = QuotaChainVerifier.deactivationReceipt(c["license"] as String, "2026-11-27", key, b64, enc)
        val out = System.getenv("QUOTA_SDK_EXPORT_DIR")
        if (out != null) {
            java.io.File(out, "android-activation-request.json").writeText(req)
            java.io.File(out, "android-deactivation-receipt.json").writeText(receipt)
        }
        for ((text, keys) in listOf(
            req to setOf("type", "snHash", "deviceIdSaltId", "devicePublicKey", "platform", "bundleName", "createdAt", "nonce"),
            receipt to setOf("type", "quotaId", "seq", "snHash", "licenseSha256", "devicePublicKey", "createdAt", "nonce"),
        )) {
            val env = StrictJson.parse(text) as Map<String, Any?>
            val payload = b64(env["payload_b64"] as String)
            val claims = StrictJson.parse(String(payload, Charsets.UTF_8)) as Map<String, Any?>
            assertEquals(keys, claims.keys)
            assertEquals(c["deviceKeySpki"], claims["devicePublicKey"])
            val pub = KeyFactory.getInstance("EC").generatePublic(java.security.spec.X509EncodedKeySpec(b64(c["deviceKeySpki"] as String)))
            assertTrue(Signature.getInstance("SHA256withECDSA").run { initVerify(pub); update(payload); verify(b64(env["sig_b64"] as String)) })
            assertFalse(text.contains("SN0000ABCD"))
        }
        assertEquals(1L, ((StrictJson.parse(String(b64((StrictJson.parse(receipt) as Map<String, Any?>)["payload_b64"] as String))) as Map<String, Any?>)["seq"]))
    }

    companion object {
        internal fun newSoftKey(): QuotaChainVerifier.DeviceKey {
            val kp = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
            return SoftKey(kp.private.encoded, kp.public.encoded)
        }
    }
}
