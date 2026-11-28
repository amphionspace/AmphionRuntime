package com.amphion.asr.internal

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.util.Base64
import com.amphion.asr.AmphionDeviceIdProvider
import com.amphion.asr.AmphionLicenseStatus
import com.amphion.asr.AsrErrorCode
import org.json.JSONObject
import java.security.KeyFactory
import java.security.MessageDigest
import java.security.Signature
import java.security.spec.X509EncodedKeySpec
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

/**
 * 离线 license 验签 + 绑定校验。纯本地、零网络。
 *
 * 信封格式（`.lic` 文件，UTF-8 JSON）：
 * ```
 * { "payload_b64": "<base64(UTF-8 JSON of claims)>",
 *   "alg": "SHA256withECDSA",
 *   "sig_b64": "<base64(DER ECDSA-P256 signature over the DECODED payload bytes)>" }
 * ```
 *
 * 设计要点（第一性原理）：
 * - 签名覆盖的是「payload_b64 解码后的原始字节」，不是重新序列化的 JSON——规避 canonical
 *   JSON 歧义，保证 Python 签发端与本端逐字节一致。
 * - 算法 ECDSA P-256 + SHA256：minSdk 24 全覆盖（Ed25519 需 API 33，故不用）。
 * - Base64 一律 [Base64.NO_WRAP]（标准字母表、无换行），与 Python `base64.b64encode` 对齐。
 * - 公钥由构建期注入（`BuildConfig.LICENSE_PUBLIC_KEY_B64`），本类只接收字符串参数，便于测试。
 */
/** 授权时钟水位：记录已见过的最大日期（yyyy-MM-dd），离线设备把时钟调回也不能让过期授权复活。 */
internal interface LicenseClock {
    fun read(): String
    fun write(day: String)
}

/** 水位存到应用私有 SharedPreferences；只增不减。读写失败时退化为只用设备时钟。 */
internal class PrefsLicenseClock(ctx: Context) : LicenseClock {
    private val prefs = runCatching { ctx.getSharedPreferences("amphion_license_clock", Context.MODE_PRIVATE) }.getOrNull()
    override fun read(): String = runCatching { prefs?.getString(KEY, "") ?: "" }.getOrDefault("")
    override fun write(day: String) {
        runCatching { if (read() < day) prefs?.edit()?.putString(KEY, day)?.commit() }
    }
    private companion object { const val KEY = "maxSeenDate" }
}

internal object LicenseVerifier {

    private const val DAY_MS = 24L * 60 * 60 * 1000

    /** 校验结果：成功时 [errorCode] = [AsrErrorCode.OK]。 */
    internal class Result(
        val status: AmphionLicenseStatus,
        val errorCode: Int,
        val errorMessage: String?,
    ) {
        val ok: Boolean get() = errorCode == AsrErrorCode.OK
    }

    /**
     * 执行校验。
     *
     * @param publicKeyB64 构建期注入的一个或多个 X.509 SubjectPublicKeyInfo（DER）的 base64；
     *   多个信任根用逗号分隔，便于密钥轮换并兼容已签发 license；
     *   空白表示 SDK 未武装 license → 返回 [AmphionLicenseStatus.State.DEV_UNLICENSED]
     * @param licenseText `.lic` 文件全文；可空（武装态下为空即 [AsrErrorCode.LICENSE_MISSING]）
     * @param expiryGraceDays 过期宽限天数（规避客户端时钟误差）
     * @param nowMillis 当前时间（可注入用于测试）
     */
    fun verify(
        ctx: Context,
        licenseText: String?,
        publicKeyB64: String,
        expiryGraceDays: Int,
        deviceIdProvider: AmphionDeviceIdProvider? = null,
        sdkMajor: Int = 1,
        sdkReleaseDate: String = "",
        requiredFeature: String = "ASR",
        nowMillis: Long = System.currentTimeMillis(),
        quotaDeviceKey: (() -> QuotaChainVerifier.DeviceKey)? = null,
        clock: LicenseClock? = null,
    ): Result {
        val pkg = ctx.packageName ?: ""

        // 1. 未武装：开发 / 内部构建，跳过一切校验。
        if (publicKeyB64.isBlank()) {
            return Result(dev(pkg), AsrErrorCode.OK, null)
        }

        // 2. 缺 license。
        if (licenseText.isNullOrBlank()) {
            return fail(pkg, AsrErrorCode.LICENSE_MISSING, "no license provided")
        }

        // 2b. 按数量离线授权（额度证书链）：由顶层 format 字段区分，与 SN 白名单格式互斥。
        if (QuotaChainVerifier.isChain(licenseText)) {
            val serial = runCatching { deviceIdProvider?.getDeviceSerial(ctx) }.getOrNull() ?: ""
            return verifyQuotaChain(
                licenseText, publicKeyB64, pkg, serial, sdkMajor, sdkReleaseDate, requiredFeature, nowMillis,
                quotaDeviceKey?.invoke() ?: keystoreKeyOrMissing(), clock ?: PrefsLicenseClock(ctx),
            ) { Base64.decode(it, Base64.NO_WRAP) }
        }

        // 3. 解析信封 + payload + 签名字节。
        val payloadBytes: ByteArray
        val sigBytes: ByteArray
        try {
            val env = JSONObject(licenseText)
            payloadBytes = Base64.decode(env.getString("payload_b64"), Base64.NO_WRAP)
            sigBytes = Base64.decode(env.getString("sig_b64"), Base64.NO_WRAP)
        } catch (t: Throwable) {
            return fail(pkg, AsrErrorCode.LICENSE_MALFORMED, "bad envelope: ${t.message}")
        }

        // 4. 解析 claims（payload 原始字节 → JSON）。
        val claims: LicenseClaims = try {
            parseClaims(String(payloadBytes, Charsets.UTF_8))
        } catch (t: Throwable) {
            return fail(pkg, AsrErrorCode.LICENSE_MALFORMED, "bad payload: ${t.message}")
        }

        // 5. ECDSA 验签（对 payload 原始字节）。
        val signatureValid = verifyWithAnyTrustedKey(payloadBytes, sigBytes, publicKeyB64)
        if (!signatureValid) {
            return failWith(claims, AsrErrorCode.LICENSE_SIGNATURE_INVALID, "signature mismatch")
        }

        // 6. 应用包白名单。旧 license 没有策略字段，继续按原有 ASR 语义仅记录。
        if (!applicationMatches(claims.applicationBindingMode, claims.boundApplicationId, claims.applicationIds, pkg)) {
            return failWith(claims, AsrErrorCode.LICENSE_APP_MISMATCH, "license application policy rejected host=$pkg")
        }

        // 7. 签名证书绑定（signingCertDigest 非空时才校验；兼容旧 certSha256）。
        if (claims.boundSigningCertDigest.isNotBlank()) {
            val want = normalizeHex(claims.boundSigningCertDigest)
            val have = hostCertSha256Set(ctx)
            if (!have.contains(want)) {
                return failWith(
                    claims,
                    AsrErrorCode.LICENSE_CERT_MISMATCH,
                    "license cert=$want host=${have.joinToString(",")}",
                )
            }
        }

        // 7. 到期校验（expiresAt 非空时才校验；到期日当天有效，再加宽限）。
        if (claims.expiresAt.isNotBlank()) {
            val expMillis = parseDateUtcMillis(claims.expiresAt)
                ?: return failWith(claims, AsrErrorCode.LICENSE_MALFORMED, "bad expiresAt=${claims.expiresAt}")
            val deadline = expMillis + (expiryGraceDays + 1).toLong() * DAY_MS
            if (nowMillis >= deadline) {
                return failWith(claims, AsrErrorCode.LICENSE_EXPIRED, "expiresAt=${claims.expiresAt}")
            }
        }

        // 8. SDK 大版本和维护期校验。维护期控制可升级版本，不影响已授权旧版本运行。
        if (!sdkMajorMatches(claims.sdkMajor, sdkMajor)) {
            return failWith(
                claims,
                AsrErrorCode.LICENSE_SDK_MAJOR_MISMATCH,
                "license sdkMajor=${claims.sdkMajor} host=$sdkMajor",
            )
        }
        if (claims.maintenanceUntil.isNotBlank() && sdkReleaseDate.isNotBlank()) {
            val releaseMillis = parseDateUtcMillis(sdkReleaseDate)
                ?: return failWith(claims, AsrErrorCode.LICENSE_MALFORMED, "bad sdkReleaseDate=$sdkReleaseDate")
            val maintenanceMillis = parseDateUtcMillis(claims.maintenanceUntil)
                ?: return failWith(
                    claims,
                    AsrErrorCode.LICENSE_MALFORMED,
                    "bad maintenanceUntil=${claims.maintenanceUntil}",
                )
            if (releaseMillis > maintenanceMillis) {
                return failWith(
                    claims,
                    AsrErrorCode.LICENSE_MAINTENANCE_EXPIRED,
                    "maintenanceUntil=${claims.maintenanceUntil} sdkReleaseDate=$sdkReleaseDate",
                )
            }
        }

        // 9. 能力授权。当前 license 只按 ASR / TTS 两类授权，不再细分语言或增强能力。
        val normalizedFeatures = claims.features.map { it.trim().uppercase(Locale.ROOT) }.toSet()
        if (!normalizedFeatures.contains(requiredFeature.uppercase(Locale.ROOT))) {
            return failWith(
                claims,
                AsrErrorCode.LICENSE_FEATURE_MISSING,
                "license features=${claims.features.joinToString(",")} missing $requiredFeature",
            )
        }

        // 10. SN 白名单绑定。新 license 使用 authorizedDeviceHashes；旧 deviceSha256 仅保留兼容。
        if (claims.authorizedDeviceHashes.isNotEmpty()) {
            if (!claims.deviceIdHashAlg.equals("SHA-256", ignoreCase = true)) {
                return failWith(claims, AsrErrorCode.LICENSE_MALFORMED, "unsupported deviceIdHashAlg=${claims.deviceIdHashAlg}")
            }
            val have = DeviceLicenseFingerprint.compute(ctx, deviceIdProvider, claims.deviceIdSaltId)
                ?: return failWith(claims, AsrErrorCode.LICENSE_DEVICE_MISMATCH, "device SN unavailable")
            if (!claims.authorizedDeviceHashes.contains(have)) {
                return failWith(
                    claims,
                    AsrErrorCode.LICENSE_DEVICE_MISMATCH,
                    "device hash not authorized",
                )
            }
        } else if (claims.deviceSha256.isNotBlank()) {
            val have = DeviceLicenseFingerprint.compute(ctx, deviceIdProvider, claims.deviceIdSaltId)
                ?: return failWith(claims, AsrErrorCode.LICENSE_DEVICE_MISMATCH, "device SN unavailable")
            if (normalizeHex(claims.deviceSha256) != have) {
                return failWith(claims, AsrErrorCode.LICENSE_DEVICE_MISMATCH, "legacy device hash mismatch")
            }
        }

        // 全部通过。
        return Result(
            AmphionLicenseStatus(
                state = AmphionLicenseStatus.State.LICENSED,
                valid = true,
                errorCode = AsrErrorCode.OK,
                licenseId = claims.licenseId,
                customer = claims.customer,
                applicationId = claims.boundApplicationId,
                bundleName = claims.bundleName,
                signingCertDigest = claims.boundSigningCertDigest,
                deviceIdHashAlg = claims.deviceIdHashAlg,
                deviceIdSaltId = claims.deviceIdSaltId,
                authorizedDeviceCount = claims.authorizedDeviceHashes.size,
                maintenanceUntil = claims.maintenanceUntil,
                issuedAt = claims.issuedAt,
                expiresAt = claims.expiresAt,
                installTier = claims.installTier,
                features = claims.features,
            ),
            AsrErrorCode.OK,
            null,
        )
    }

    /**
     * 额度证书链校验（纯 JVM，可单测）。设备日期取设备时钟与水位中较晚者，校验通过后推进水位。
     * 链格式只在武装构建放行：未注入根公钥时没有信任起点（NOT_ARMED → LICENSE_MALFORMED）。
     */
    internal fun verifyQuotaChain(
        text: String,
        publicKeyB64: String,
        pkg: String,
        serial: String,
        sdkMajor: Int,
        sdkReleaseDate: String,
        requiredFeature: String,
        nowMillis: Long,
        deviceKey: QuotaChainVerifier.DeviceKey,
        clock: LicenseClock,
        b64: (String) -> ByteArray,
    ): Result {
        val deviceToday = SimpleDateFormat("yyyy-MM-dd", Locale.ROOT)
            .apply { timeZone = TimeZone.getTimeZone("UTC") }.format(java.util.Date(nowMillis))
        val watermark = clock.read()
        val today = QuotaChainVerifier.effectiveToday(deviceToday, watermark)
        val ctx = QuotaChainVerifier.Context(serial, pkg, sdkMajor, sdkReleaseDate, requiredFeature.uppercase(Locale.ROOT),
            today, deviceKey)
        val r = try {
            QuotaChainVerifier.verify(text, publicKeyB64, ctx, b64)
        } catch (e: QuotaChainVerifier.ChainException) {
            return fail(pkg, QuotaChainVerifier.errorCodeOf(e.code), "quota license rejected: ${e.code}")
        }
        if (today != watermark) clock.write(today)
        return Result(
            AmphionLicenseStatus(
                state = AmphionLicenseStatus.State.LICENSED,
                valid = true,
                errorCode = AsrErrorCode.OK,
                licenseId = "${r.quotaId}#${r.seq}",
                customer = r.customer,
                applicationId = pkg,
                bundleName = "",
                signingCertDigest = "",
                deviceIdHashAlg = "SHA-256",
                deviceIdSaltId = r.deviceIdSaltId,
                authorizedDeviceCount = r.maxDevices.toInt(),
                maintenanceUntil = r.maintenanceUntil,
                issuedAt = "",
                expiresAt = r.licenseExpiresAt,
                installTier = "quota",
                features = r.features,
            ),
            AsrErrorCode.OK,
            null,
        )
    }

    /** Keystore 不可用（或密钥未生成）时返回一个总是失败的密钥，校验落到 DEVICE_KEY_MISMATCH。 */
    private fun keystoreKeyOrMissing(): QuotaChainVerifier.DeviceKey =
        runCatching { KeystoreDeviceKey() }.getOrNull() ?: object : QuotaChainVerifier.DeviceKey {
            override fun publicKeySpki(): ByteArray = throw IllegalStateException("keystore unavailable")
            override fun sign(challenge: ByteArray): ByteArray = throw IllegalStateException("keystore unavailable")
        }

    /** Accepts a comma-separated trust set so old and rotated signing keys can coexist safely. */
    internal fun verifyWithAnyTrustedKey(
        payloadBytes: ByteArray,
        signatureBytes: ByteArray,
        publicKeysB64: String,
        decodeKey: (String) -> ByteArray = { Base64.decode(it, Base64.NO_WRAP) },
    ): Boolean = publicKeysB64.split(',')
        .asSequence()
        .map(String::trim)
        .filter(String::isNotEmpty)
        .any { publicKeyB64 ->
            runCatching {
                val keyBytes = decodeKey(publicKeyB64)
                val pub = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(keyBytes))
                Signature.getInstance("SHA256withECDSA").run {
                    initVerify(pub)
                    update(payloadBytes)
                    verify(signatureBytes)
                }
            }.getOrDefault(false)
        }

    // -------- 内部 --------

    private fun parseClaims(payloadJson: String): LicenseClaims {
        val o = JSONObject(payloadJson)
        return LicenseClaims(
            licenseId = o.optString("licenseId", ""),
            customer = o.optString("customer", ""),
            applicationId = o.optString("applicationId", ""),
            bundleName = o.optString("bundleName", ""),
            applicationBindingMode = o.optString("applicationBindingMode", ""),
            applicationIds = parseStringArray(o, "applicationIds").toSet(),
            signingCertDigest = o.optString("signingCertDigest", ""),
            certSha256 = o.optString("certSha256", ""),
            deviceIdHashAlg = o.optString("deviceIdHashAlg", "SHA-256"),
            deviceIdSaltId = o.optString("deviceIdSaltId", ""),
            authorizedDeviceHashes = parseStringArray(o, "authorizedDeviceHashes")
                .map(::normalizeHex)
                .filter { it.isNotEmpty() }
                .toSet(),
            deviceSha256 = o.optString("deviceSha256", ""),
            issuedAt = o.optString("issuedAt", ""),
            expiresAt = o.optString("expiresAt", ""),
            maintenanceUntil = o.optString("maintenanceUntil", ""),
            installTier = o.optString("installTier", ""),
            features = parseStringArray(o, "features"),
            sdkMajor = o.optInt("sdkMajor", -1),
        )
    }

    internal fun sdkMajorMatches(licensedMajor: Int, runtimeMajor: Int): Boolean =
        licensedMajor <= 0 || runtimeMajor <= 0 || licensedMajor == runtimeMajor

    internal fun applicationMatches(mode: String, licensedApp: String, applicationIds: Set<String>, runtimeApp: String): Boolean =
        when (mode.trim().lowercase(Locale.ROOT)) {
            "", "none", "record-only" -> true
            "bound" -> licensedApp.isNotBlank() && licensedApp == runtimeApp
            "allowlist" -> applicationIds.isNotEmpty() && applicationIds.contains(runtimeApp)
            else -> false
        }

    private fun parseStringArray(o: JSONObject, key: String): List<String> {
        val arr = o.optJSONArray(key) ?: return emptyList()
        return (0 until arr.length()).mapNotNull { i ->
            arr.optString(i, "").trim().takeIf { it.isNotEmpty() }
        }
    }

    /** 读取宿主 app 的签名证书 SHA-256 集合（大写、无冒号）。兼容 API 24~27 与 28+。 */
    private fun hostCertSha256Set(ctx: Context): Set<String> {
        val pm = ctx.packageManager
        val sigs: Array<android.content.pm.Signature> = try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                val info = pm.getPackageInfo(ctx.packageName, PackageManager.GET_SIGNING_CERTIFICATES)
                val si = info.signingInfo
                when {
                    si == null -> emptyArray()
                    si.hasMultipleSigners() -> si.apkContentsSigners
                    else -> si.signingCertificateHistory ?: si.apkContentsSigners
                }
            } else {
                @Suppress("DEPRECATION")
                pm.getPackageInfo(ctx.packageName, PackageManager.GET_SIGNATURES).signatures ?: emptyArray()
            }
        } catch (_: Throwable) {
            emptyArray()
        }
        return sigs.mapNotNull { s ->
            try {
                sha256HexNoColon(s.toByteArray())
            } catch (_: Throwable) {
                null
            }
        }.toSet()
    }

    private fun sha256HexNoColon(bytes: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
        val sb = StringBuilder(digest.size * 2)
        for (b in digest) sb.append(String.format(Locale.ROOT, "%02X", b.toInt() and 0xFF))
        return sb.toString()
    }

    private fun normalizeHex(s: String): String =
        s.replace(":", "").replace(" ", "").uppercase(Locale.ROOT)

    private fun parseDateUtcMillis(s: String): Long? = try {
        SimpleDateFormat("yyyy-MM-dd", Locale.ROOT).apply {
            timeZone = TimeZone.getTimeZone("UTC")
            isLenient = false
        }.parse(s)?.time
    } catch (_: Throwable) {
        null
    }

    private fun dev(pkg: String): AmphionLicenseStatus = AmphionLicenseStatus(
        state = AmphionLicenseStatus.State.DEV_UNLICENSED,
        valid = false,
        errorCode = AsrErrorCode.OK,
        licenseId = "",
        customer = "",
        applicationId = pkg,
        bundleName = "",
        signingCertDigest = "",
        deviceIdHashAlg = "",
        deviceIdSaltId = "",
        authorizedDeviceCount = 0,
        maintenanceUntil = "",
        issuedAt = "",
        expiresAt = "",
        installTier = "",
        features = emptyList(),
    )

    private fun fail(pkg: String, code: Int, msg: String): Result = Result(
        AmphionLicenseStatus(
            state = AmphionLicenseStatus.State.INVALID,
            valid = false,
            errorCode = code,
            licenseId = "",
            customer = "",
            applicationId = pkg,
            bundleName = "",
            signingCertDigest = "",
            deviceIdHashAlg = "",
            deviceIdSaltId = "",
            authorizedDeviceCount = 0,
            maintenanceUntil = "",
            issuedAt = "",
            expiresAt = "",
            installTier = "",
            features = emptyList(),
        ),
        code,
        msg,
    )

    /** 失败但已解析出 claims：尽量把客户 / 到期等信息带进 status，便于排障展示。 */
    private fun failWith(claims: LicenseClaims, code: Int, msg: String): Result = Result(
        AmphionLicenseStatus(
            state = AmphionLicenseStatus.State.INVALID,
            valid = false,
            errorCode = code,
            licenseId = claims.licenseId,
            customer = claims.customer,
            applicationId = claims.boundApplicationId,
            bundleName = claims.bundleName,
            signingCertDigest = claims.boundSigningCertDigest,
            deviceIdHashAlg = claims.deviceIdHashAlg,
            deviceIdSaltId = claims.deviceIdSaltId,
            authorizedDeviceCount = claims.authorizedDeviceHashes.size,
            maintenanceUntil = claims.maintenanceUntil,
            issuedAt = claims.issuedAt,
            expiresAt = claims.expiresAt,
            installTier = claims.installTier,
            features = claims.features,
        ),
        code,
        msg,
    )
}
