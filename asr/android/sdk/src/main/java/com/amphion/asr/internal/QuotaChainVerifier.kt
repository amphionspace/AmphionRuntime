package com.amphion.asr.internal

import com.amphion.asr.AsrErrorCode
import java.security.KeyFactory
import java.security.MessageDigest
import java.security.PublicKey
import java.security.SecureRandom
import java.security.Signature
import java.security.interfaces.ECPublicKey
import java.security.spec.X509EncodedKeySpec
import java.util.Locale

/**
 * 按数量离线授权（额度证书链 amphion.quota-chain.v1）的设备端校验。纯本地、零网络、纯 JVM。
 *
 * 信任链：SDK 内置根公钥 → 额度证书（数量 N、能力、期限、签发点公钥）→ 签发点签的设备授权
 * （seq∈[1,N]、SN 哈希、设备公钥摘要）→ 设备密钥对随机挑战的签名（AndroidKeyStore/HUKS）。
 *
 * 与签发端 tools/license/quota/quota_chain.py 的 verify_chain 逐条对齐，错误码字符串相同；
 * 两端用同一批 Python 签出的用例互测（QuotaChainVerifierTest）。
 */
internal object QuotaChainVerifier {

    const val FORMAT = "amphion.quota-chain.v1"
    private const val ALG = "SHA256withECDSA"
    private const val T_QUOTA = "amphion.quota.v1"
    private const val T_DEVICE = "amphion.device-license.v1"
    private const val T_CHALLENGE = "amphion.device-challenge.v1"
    private const val T_ACTIVATION = "amphion.activation-request.v1"
    private const val T_DEACT = "amphion.deactivation-receipt.v1"
    private const val MAX_BYTES = 64 * 1024
    private const val MAX_DEVICES = 1_000_000L
    private val DATE = Regex("^\\d{4}-\\d{2}-\\d{2}$")
    private val HEX64 = Regex("^[0-9A-F]{64}$")
    private val SALT = Regex("^[A-Za-z0-9_-]{8,120}$")
    private val ID = Regex("^[A-Za-z0-9._-]{1,80}$")
    private val SERIAL = Regex("^[A-Z0-9]{4,64}$")
    private val FEATURES = setOf("ASR", "TTS")

    class ChainException(val code: String, detail: String = "") : Exception(if (detail.isEmpty()) code else "$code: $detail")

    /** 设备密钥：真机由 [KeystoreDeviceKey] 实现，私钥不可导出。 */
    interface DeviceKey {
        fun publicKeySpki(): ByteArray
        fun sign(challenge: ByteArray): ByteArray
    }

    class Context(
        val serial: String,
        val bundleName: String,
        val sdkMajor: Int,
        val sdkReleaseDate: String,
        val requiredFeature: String,
        val today: String,
        val deviceKey: DeviceKey,
    )

    class Result(val quotaId: String, val seq: Long, val maxDevices: Long, val features: List<String>,
                 val licenseExpiresAt: String, val customer: String, val maintenanceUntil: String = "",
                 val deviceIdSaltId: String = "")

    /**
     * 时钟水位：取设备时钟与已见最大日期中较晚者。离线设备调回时钟不能让已过期的授权复活。
     * 调用方在校验通过后把返回值存回本地（只增不减）。
     */
    fun effectiveToday(deviceToday: String, watermark: String): String =
        if (DATE.matches(watermark) && watermark > deviceToday) watermark else deviceToday

    /** 生成交给签发点的激活请求（不含明文 SN）。platform: android_arm64 / harmony_arm64。 */
    fun activationRequest(serial: String, saltId: String, platform: String, bundleName: String, today: String,
                          key: DeviceKey, b64e: (ByteArray) -> String): String {
        val normalized = serial.trim().uppercase(Locale.ROOT)
        if (!SERIAL.matches(normalized) || !SALT.matches(saltId) || !DATE.matches(today))
            throw ChainException("MALFORMED", "activation input")
        return signedEnvelope(linkedMapOf(
            "type" to T_ACTIVATION,
            "snHash" to sha256Hex((normalized + saltId).toByteArray(Charsets.UTF_8)),
            "deviceIdSaltId" to saltId,
            "devicePublicKey" to b64e(key.publicKeySpki()),
            "platform" to platform,
            "bundleName" to bundleName,
            "createdAt" to today,
            "nonce" to nonceHex(),
        ), key, b64e)
    }

    /** 注销回执：调用方签完后必须立即销毁设备密钥和授权文件。 */
    fun deactivationReceipt(licenseText: String, today: String, key: DeviceKey,
                            b64: (String) -> ByteArray, b64e: (ByteArray) -> String): String {
        val top = exact(parseJson(licenseText), setOf("format", "quota", "device"), "chain")
        val quotaEnv = exact(top["quota"], setOf("alg", "payload_b64", "sig_b64"), "envelope")
        @Suppress("UNCHECKED_CAST")
        val quota = parseJson(String(decode(quotaEnv["payload_b64"], b64), Charsets.UTF_8)) as? Map<String, Any?>
            ?: throw ChainException("MALFORMED", "quota")
        val sitePub = decodeKey(b64(quota.obj("site").str("publicKey")))
        val (dBytes, dev) = open(top["device"], listOf(sitePub), T_DEVICE, "DEVICE_SIGNATURE_INVALID", b64)
        return signedEnvelope(linkedMapOf(
            "type" to T_DEACT,
            "quotaId" to dev.str("quotaId"),
            "seq" to dev.long("seq"),
            "snHash" to dev.str("snHash"),
            "licenseSha256" to sha256Hex(dBytes),
            "devicePublicKey" to b64e(key.publicKeySpki()),
            "createdAt" to today,
            "nonce" to nonceHex(),
        ), key, b64e)
    }

    private fun signedEnvelope(claims: Map<String, Any>, key: DeviceKey, b64e: (ByteArray) -> String): String {
        val payload = claims.entries.joinToString(",", "{", "}") { (k, v) ->
            "${jsonString(k)}:${if (v is Long) v.toString() else jsonString(v as String)}"
        }.toByteArray(Charsets.UTF_8)
        val sig = key.sign(payload)
        return "{\"payload_b64\":${jsonString(b64e(payload))},\"alg\":\"$ALG\",\"sig_b64\":${jsonString(b64e(sig))}}"
    }

    private fun jsonString(v: String): String {
        val sb = StringBuilder("\"")
        for (c in v) when {
            c == '"' -> sb.append("\\\"")
            c == '\\' -> sb.append("\\\\")
            c < ' ' -> sb.append(String.format(Locale.ROOT, "\\u%04x", c.code))
            else -> sb.append(c)
        }
        return sb.append('"').toString()
    }

    private fun nonceHex(): String =
        ByteArray(16).also { SecureRandom().nextBytes(it) }.joinToString("") { String.format(Locale.ROOT, "%02x", it) }

    /** 判断文件是不是链格式（供 SDK 在旧白名单格式与链格式之间分派）。 */
    fun isChain(text: String): Boolean = try {
        (StrictJson.parse(text) as? Map<*, *>)?.get("format") == FORMAT
    } catch (_: Exception) { false }

    fun verify(text: String, trustedRootsB64: String, ctx: Context, b64: (String) -> ByteArray): Result {
        val roots = trustedRootsB64.split(',').map { it.trim() }.filter { it.isNotEmpty() }
        if (roots.isEmpty()) throw ChainException("NOT_ARMED")
        if (text.toByteArray(Charsets.UTF_8).size > MAX_BYTES * 3) throw ChainException("MALFORMED", "too large")
        val top = exact(parseJson(text), setOf("format", "quota", "device"), "chain")
        if (top["format"] != FORMAT) throw ChainException("MALFORMED", "format")

        // 1. 额度证书只认内置根公钥。
        val (qBytes, quota) = open(top["quota"], roots.map { decodeKey(b64(it)) }, T_QUOTA, "QUOTA_SIGNATURE_INVALID", b64)
        validateQuota(quota, b64)
        val site = quota.obj("site")
        val qSha = sha256Hex(qBytes)

        // 2. 设备授权只认额度证书里写明的签发点公钥。
        val sitePub = decodeKey(b64(site.str("publicKey")))
        val (_, dev) = open(top["device"], listOf(sitePub), T_DEVICE, "DEVICE_SIGNATURE_INVALID", b64)
        validateDevice(dev)
        if (dev.str("quotaSha256") != qSha || dev.str("quotaId") != quota.str("quotaId"))
            throw ChainException("QUOTA_MISMATCH", "device license references another quota")
        if (dev.str("siteKeyId") != site.str("keyId")) throw ChainException("QUOTA_MISMATCH", "site key id")

        // 3. 数量上限。
        val seq = dev.long("seq")
        val max = quota.long("maxDevices")
        if (seq < 1 || seq > max) throw ChainException("SEQ_OUT_OF_RANGE", "seq=$seq max=$max")

        // 4. 签发点不能放大权限。
        val qFeatures = quota.strList("features")
        val dFeatures = dev.strList("features")
        if (dFeatures.isEmpty() || dFeatures.any { it !in qFeatures }) throw ChainException("FEATURE_ESCALATION")
        if (ctx.requiredFeature !in dFeatures) throw ChainException("FEATURE_MISSING", ctx.requiredFeature)
        val issued = dev.str("issuedAt")
        if (issued < quota.str("issuedAt") || issued > quota.str("issueNotAfter")) throw ChainException("ISSUE_WINDOW")
        val qExp = quota.str("licenseExpiresAt")
        val dExp = dev.str("licenseExpiresAt")
        if (qExp.isNotEmpty() && (dExp.isEmpty() || dExp > qExp)) throw ChainException("EXPIRY_ESCALATION")
        if (dev.str("deviceIdSaltId") != quota.str("deviceIdSaltId")) throw ChainException("QUOTA_MISMATCH", "salt")

        // 5. 运行期限 / 版本 / 维护期 / 应用包（策略只取自根签的额度证书）。
        if (dExp.isNotEmpty() && ctx.today > dExp) throw ChainException("EXPIRED", dExp)
        val major = quota.long("sdkMajor")
        if (major > 0 && major != ctx.sdkMajor.toLong()) throw ChainException("SDK_MAJOR_MISMATCH")
        val maint = quota.str("maintenanceUntil")
        if (maint.isNotEmpty() && ctx.sdkReleaseDate.isNotEmpty() && ctx.sdkReleaseDate > maint)
            throw ChainException("MAINTENANCE_EXPIRED", maint)
        if (quota.str("applicationBindingMode") == "allowlist" &&
            ctx.bundleName !in (quota.strList("bundleNames") + quota.strList("applicationIds")))
            throw ChainException("APP_MISMATCH")

        // 6. 设备绑定：SN 哈希 + 设备密钥持有证明（每次新随机挑战）。
        val normalized = ctx.serial.trim().uppercase(Locale.ROOT)
        if (!SERIAL.matches(normalized)) throw ChainException("DEVICE_ID_INVALID")
        if (sha256Hex((normalized + quota.str("deviceIdSaltId")).toByteArray(Charsets.UTF_8)) != dev.str("snHash"))
            throw ChainException("DEVICE_MISMATCH", "SN")
        val spki = try { ctx.deviceKey.publicKeySpki() } catch (_: Exception) {
            throw ChainException("DEVICE_KEY_MISMATCH", "device key unavailable")
        }
        if (sha256Hex(spki) != dev.str("devicePublicKeySha256")) throw ChainException("DEVICE_KEY_MISMATCH")
        val nonce = ByteArray(16).also { SecureRandom().nextBytes(it) }
        val challenge = (T_CHALLENGE + "|" + nonce.joinToString("") { String.format(Locale.ROOT, "%02x", it) })
            .toByteArray(Charsets.UTF_8)
        val ok = try {
            ecdsaVerify(decodeKey(spki), challenge, ctx.deviceKey.sign(challenge))
        } catch (_: Exception) { false }
        if (!ok) throw ChainException("DEVICE_KEY_MISMATCH", "challenge signature")
        return Result(quota.str("quotaId"), seq, max, dFeatures, dExp, quota.str("customer"), maint,
            quota.str("deviceIdSaltId"))
    }

    /** 映射到 SDK 已有错误码，宿主 App 不需要新增分支。 */
    fun errorCodeOf(code: String): Int = when (code) {
        "NOT_ARMED", "MALFORMED", "TYPE_MISMATCH", "DEVICE_ID_INVALID" -> AsrErrorCode.LICENSE_MALFORMED
        "QUOTA_SIGNATURE_INVALID", "DEVICE_SIGNATURE_INVALID", "QUOTA_MISMATCH", "SEQ_OUT_OF_RANGE",
        "FEATURE_ESCALATION", "ISSUE_WINDOW", "EXPIRY_ESCALATION" -> AsrErrorCode.LICENSE_SIGNATURE_INVALID
        "FEATURE_MISSING" -> AsrErrorCode.LICENSE_FEATURE_MISSING
        "EXPIRED" -> AsrErrorCode.LICENSE_EXPIRED
        "SDK_MAJOR_MISMATCH" -> AsrErrorCode.LICENSE_SDK_MAJOR_MISMATCH
        "MAINTENANCE_EXPIRED" -> AsrErrorCode.LICENSE_MAINTENANCE_EXPIRED
        "APP_MISMATCH" -> AsrErrorCode.LICENSE_APP_MISMATCH
        "DEVICE_MISMATCH", "DEVICE_KEY_MISMATCH" -> AsrErrorCode.LICENSE_DEVICE_MISMATCH
        else -> AsrErrorCode.LICENSE_MALFORMED
    }

    // ------------------------------------------------------------ 信封

    private fun open(env: Any?, keys: List<PublicKey>, type: String, sigCode: String,
                     b64: (String) -> ByteArray): Pair<ByteArray, Map<String, Any?>> {
        val e = exact(env, setOf("alg", "payload_b64", "sig_b64"), "envelope")
        if (e["alg"] != ALG) throw ChainException("MALFORMED", "alg")
        val payload = decode(e["payload_b64"], b64)
        val sig = decode(e["sig_b64"], b64)
        if (payload.size > MAX_BYTES) throw ChainException("MALFORMED", "payload too large")
        if (keys.none { k -> runCatching { ecdsaVerify(k, payload, sig) }.getOrDefault(false) })
            throw ChainException(sigCode, type)
        @Suppress("UNCHECKED_CAST")
        val claims = parseJson(String(payload, Charsets.UTF_8)) as? Map<String, Any?>
            ?: throw ChainException("MALFORMED", "claims")
        if (claims["type"] != type) throw ChainException("TYPE_MISMATCH", type)
        return payload to claims
    }

    private fun decode(v: Any?, b64: (String) -> ByteArray): ByteArray {
        if (v !is String) throw ChainException("MALFORMED", "base64")
        return try { b64(v) } catch (_: Exception) { throw ChainException("MALFORMED", "base64") }
    }

    private fun decodeKey(der: ByteArray): PublicKey {
        val k = try {
            KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(der))
        } catch (_: Exception) { throw ChainException("MALFORMED", "public key") }
        if (k !is ECPublicKey || k.params.curve.field.fieldSize != 256) throw ChainException("MALFORMED", "P-256 only")
        return k
    }

    private fun ecdsaVerify(k: PublicKey, data: ByteArray, sig: ByteArray): Boolean =
        Signature.getInstance(ALG).run { initVerify(k); update(data); verify(sig) }

    // ------------------------------------------------------------ 结构校验（与 Python validate_* 对齐）

    private fun validateQuota(q: Map<String, Any?>, b64: (String) -> ByteArray) {
        exact(q, setOf("type", "quotaId", "customer", "projectId", "issuedAt", "issueNotAfter", "licenseExpiresAt",
            "maxDevices", "features", "sdkMajor", "maintenanceUntil", "deviceIdSaltId", "applicationBindingMode",
            "bundleNames", "applicationIds", "site", "enrollmentSha256", "reassignment"), "quota")
        q.str("quotaId", ID); q.str("customer"); q.str("projectId", ID)
        val issued = date(q, "issuedAt"); val notAfter = date(q, "issueNotAfter")
        val exp = date(q, "licenseExpiresAt", allowEmpty = true)
        if (notAfter < issued || (exp.isNotEmpty() && exp < notAfter)) throw ChainException("MALFORMED", "quota dates")
        q.long("maxDevices", 1, MAX_DEVICES)
        val f = q.strList("features")
        if (f.isEmpty() || f.toSet().size != f.size || f.any { it !in FEATURES }) throw ChainException("MALFORMED", "features")
        q.long("sdkMajor", 0, 1000)
        date(q, "maintenanceUntil", allowEmpty = true)
        q.str("deviceIdSaltId", SALT)
        val mode = q.str("applicationBindingMode")
        if (mode != "none" && mode != "allowlist") throw ChainException("MALFORMED", "applicationBindingMode")
        val pk = q.strList("bundleNames") + q.strList("applicationIds")
        if ((mode == "allowlist") != pk.isNotEmpty()) throw ChainException("MALFORMED", "package policy")
        val site = exact(q["site"], setOf("siteId", "publicKey", "keyId", "hardware", "minHardwarePresent"), "site")
        val sitePk = b64(site.str("publicKey"))
        decodeKey(sitePk)
        if (site.str("keyId") != sha256Hex(sitePk)) throw ChainException("MALFORMED", "site keyId")
        q.str("enrollmentSha256", HEX64)
        exact(q["reassignment"], setOf("mode", "budget"), "reassignment")
    }

    private fun validateDevice(d: Map<String, Any?>) {
        exact(d, setOf("type", "licenseId", "quotaId", "quotaSha256", "siteKeyId", "seq", "snHash", "deviceIdSaltId",
            "devicePublicKeySha256", "features", "licenseExpiresAt", "issuedAt", "logIndex", "logPrevHash"), "device")
        d.str("licenseId", ID); d.str("quotaId", ID)
        for (k in listOf("quotaSha256", "siteKeyId", "snHash", "devicePublicKeySha256")) d.str(k, HEX64)
        d.long("seq", Int.MIN_VALUE.toLong(), Int.MAX_VALUE.toLong())
        d.str("deviceIdSaltId", SALT)
        val f = d.strList("features")
        if (f.toSet().size != f.size) throw ChainException("MALFORMED", "features")
        date(d, "licenseExpiresAt", allowEmpty = true); date(d, "issuedAt")
        d.long("logIndex", 0, 1L shl 40)
        val prev = d.str("logPrevHash")
        if (prev != "0".repeat(64) && !HEX64.matches(prev)) throw ChainException("MALFORMED", "logPrevHash")
    }

    private fun date(m: Map<String, Any?>, k: String, allowEmpty: Boolean = false): String {
        val v = m[k] as? String ?: throw ChainException("MALFORMED", k)
        if (allowEmpty && v.isEmpty()) return v
        if (!DATE.matches(v)) throw ChainException("MALFORMED", k)
        val (y, mo, d) = v.split('-').map { it.toInt() }
        val dim = intArrayOf(31, if ((y % 4 == 0 && y % 100 != 0) || y % 400 == 0) 29 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
        if (mo !in 1..12 || d !in 1..dim[mo - 1]) throw ChainException("MALFORMED", k)
        return v
    }

    // ------------------------------------------------------------ 小工具

    private fun parseJson(text: String): Any? = try {
        StrictJson.parse(text)
    } catch (e: StrictJson.JsonError) { throw ChainException("MALFORMED", e.message ?: "json") }

    @Suppress("UNCHECKED_CAST")
    private fun exact(v: Any?, keys: Set<String>, label: String): Map<String, Any?> {
        val m = v as? Map<String, Any?> ?: throw ChainException("MALFORMED", "$label must be an object")
        if (m.keys != keys) throw ChainException("MALFORMED", "$label fields mismatch")
        return m
    }

    @Suppress("UNCHECKED_CAST")
    private fun Map<String, Any?>.obj(k: String): Map<String, Any?> =
        this[k] as? Map<String, Any?> ?: throw ChainException("MALFORMED", k)

    private fun Map<String, Any?>.str(k: String, pattern: Regex? = null): String {
        val v = this[k] as? String ?: throw ChainException("MALFORMED", k)
        if (pattern != null && !pattern.matches(v)) throw ChainException("MALFORMED", k)
        return v
    }

    private fun Map<String, Any?>.long(k: String, lo: Long = Long.MIN_VALUE, hi: Long = Long.MAX_VALUE): Long {
        val v = this[k] as? Long ?: throw ChainException("MALFORMED", k)
        if (v < lo || v > hi) throw ChainException("MALFORMED", k)
        return v
    }

    private fun Map<String, Any?>.strList(k: String): List<String> {
        val v = this[k] as? List<*> ?: throw ChainException("MALFORMED", k)
        return v.map { it as? String ?: throw ChainException("MALFORMED", k) }
    }

    private fun sha256Hex(b: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(b).joinToString("") { String.format(Locale.ROOT, "%02X", it) }
}
