package com.lits.tts.sdk.internal

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import com.lits.tts.sdk.TtsErrorCode
import com.lits.tts.sdk.TtsDeviceIdProvider
import com.lits.tts.sdk.TtsLicenseStatus
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
 * - base64 用内部 [Base64Codec]（标准字母表、无换行），既覆盖 API 24+ 又可纯 JVM 自测。
 * - 公钥由构建期注入（`BuildConfig.LICENSE_PUBLIC_KEY_B64`），本类只接收字符串参数。
 * - 校验拆成 [verify]（从 [Context] 解析 packageName/证书/SN）+ [verifyResolved]
 *   （仅接收已解析好的字符串，无任何 Android 依赖），后者可用运行时生成的 EC 密钥离设备自测。
 */
internal object LicenseVerifier {

    private const val DAY_MS = 24L * 60 * 60 * 1000

    /** 校验结果：成功时 [errorCode] = [TtsErrorCode.OK]。 */
    internal class Result(
        val status: TtsLicenseStatus,
        val errorCode: Int,
        val errorMessage: String?,
    ) {
        val ok: Boolean get() = errorCode == TtsErrorCode.OK
    }

    /**
     * 真机校验入口：从 [ctx] 解析宿主 packageName / 签名证书 / SN 后委托 [verifyResolved]。
     *
     * @param publicKeyB64 构建期注入的 X.509 SubjectPublicKeyInfo(DER) 的 base64；
     *   空白表示 SDK 未武装 → 返回 [TtsLicenseStatus.State.DEV_UNLICENSED]
     * @param licenseText `.lic` 文件全文；可空（武装态下为空即 [TtsErrorCode.LICENSE_MISSING]）
     * @param expiryGraceDays 过期宽限天数（规避客户端时钟误差）
     * @param nowMillis 当前时间（可注入用于测试）
     */
    fun verify(
        ctx: Context,
        licenseText: String?,
        publicKeyB64: String,
        expiryGraceDays: Int,
        deviceIdProvider: TtsDeviceIdProvider? = null,
        sdkMajor: Int = 1,
        sdkReleaseDate: String = "",
        requiredFeature: String = "TTS",
        nowMillis: Long = System.currentTimeMillis(),
    ): Result {
        val pkg = runCatching { ctx.packageName }.getOrNull() ?: ""
        if (publicKeyB64.isBlank()) {
            return Result(dev(pkg), TtsErrorCode.OK, null)
        }
        val hostCerts = hostCertSha256Set(ctx)
        return verifyResolved(
            licenseText = licenseText,
            publicKeyB64 = publicKeyB64,
            packageName = pkg,
            hostCertSha256 = hostCerts,
            deviceSerial = deviceIdProvider?.getDeviceSerial(ctx),
            expiryGraceDays = expiryGraceDays,
            sdkMajor = sdkMajor,
            sdkReleaseDate = sdkReleaseDate,
            requiredFeature = requiredFeature,
            nowMillis = nowMillis,
        )
    }

    /**
     * 纯字符串校验核心（无 Android 依赖，可单测）。所有宿主侧信息由调用方解析后传入。
     */
    internal fun verifyResolved(
        licenseText: String?,
        publicKeyB64: String,
        packageName: String,
        hostCertSha256: Set<String>,
        deviceSerial: String?,
        expiryGraceDays: Int,
        sdkMajor: Int,
        sdkReleaseDate: String,
        requiredFeature: String,
        nowMillis: Long,
    ): Result {
        // 1. 未武装：开发 / 内部构建，跳过一切校验。
        if (publicKeyB64.isBlank()) {
            return Result(dev(packageName), TtsErrorCode.OK, null)
        }

        // 2. 缺 license。
        if (licenseText.isNullOrBlank()) {
            return fail(packageName, TtsErrorCode.LICENSE_MISSING, "no license provided")
        }

        // 3. 解析信封 + payload + 签名字节。
        val payloadBytes: ByteArray
        val sigBytes: ByteArray
        try {
            val env = JSONObject(licenseText)
            payloadBytes = Base64Codec.decode(env.getString("payload_b64"))
            sigBytes = Base64Codec.decode(env.getString("sig_b64"))
        } catch (t: Throwable) {
            return fail(packageName, TtsErrorCode.LICENSE_MALFORMED, "bad envelope: ${t.message}")
        }

        // 4. 解析 claims（payload 原始字节 → JSON）。
        val claims: LicenseClaims = try {
            parseClaims(String(payloadBytes, Charsets.UTF_8))
        } catch (t: Throwable) {
            return fail(packageName, TtsErrorCode.LICENSE_MALFORMED, "bad payload: ${t.message}")
        }

        // 5. ECDSA 验签（对 payload 原始字节）。
        val signatureValid: Boolean = try {
            val keyBytes = Base64Codec.decode(publicKeyB64)
            val pub = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(keyBytes))
            Signature.getInstance("SHA256withECDSA").run {
                initVerify(pub)
                update(payloadBytes)
                verify(sigBytes)
            }
        } catch (t: Throwable) {
            return failWith(claims, TtsErrorCode.LICENSE_SIGNATURE_INVALID, "verify error: ${t.message}")
        }
        if (!signatureValid) {
            return failWith(claims, TtsErrorCode.LICENSE_SIGNATURE_INVALID, "signature mismatch")
        }

        // 6. applicationId / bundleName 绑定。Android 使用 packageName 匹配统一绑定字段。
        val boundApp = claims.boundApplicationId
        if (boundApp != packageName) {
            return failWith(
                claims,
                TtsErrorCode.LICENSE_APP_MISMATCH,
                "license app=$boundApp host=$packageName",
            )
        }

        // 7. 签名证书绑定（signingCertDigest 非空时才校验；兼容旧 certSha256）。
        if (claims.boundSigningCertDigest.isNotBlank()) {
            val want = normalizeHex(claims.boundSigningCertDigest)
            if (!hostCertSha256.contains(want)) {
                return failWith(
                    claims,
                    TtsErrorCode.LICENSE_CERT_MISMATCH,
                    "license cert=$want host=${hostCertSha256.joinToString(",")}",
                )
            }
        }

        // 8. 到期校验（expiresAt 非空时才校验；到期日当天有效，再加宽限）。
        if (claims.expiresAt.isNotBlank()) {
            val expMillis = parseDateUtcMillis(claims.expiresAt)
                ?: return failWith(claims, TtsErrorCode.LICENSE_MALFORMED, "bad expiresAt=${claims.expiresAt}")
            val deadline = expMillis + (expiryGraceDays + 1).toLong() * DAY_MS
            if (nowMillis >= deadline) {
                return failWith(claims, TtsErrorCode.LICENSE_EXPIRED, "expiresAt=${claims.expiresAt}")
            }
        }

        // 9. SDK 大版本和维护期校验。
        if (claims.sdkMajor >= 0 && claims.sdkMajor != sdkMajor) {
            return failWith(
                claims,
                TtsErrorCode.LICENSE_SDK_MAJOR_MISMATCH,
                "license sdkMajor=${claims.sdkMajor} host=$sdkMajor",
            )
        }
        if (claims.maintenanceUntil.isNotBlank() && sdkReleaseDate.isNotBlank()) {
            val releaseMillis = parseDateUtcMillis(sdkReleaseDate)
                ?: return failWith(claims, TtsErrorCode.LICENSE_MALFORMED, "bad sdkReleaseDate=$sdkReleaseDate")
            val maintenanceMillis = parseDateUtcMillis(claims.maintenanceUntil)
                ?: return failWith(
                    claims,
                    TtsErrorCode.LICENSE_MALFORMED,
                    "bad maintenanceUntil=${claims.maintenanceUntil}",
                )
            if (releaseMillis > maintenanceMillis) {
                return failWith(
                    claims,
                    TtsErrorCode.LICENSE_MAINTENANCE_EXPIRED,
                    "maintenanceUntil=${claims.maintenanceUntil} sdkReleaseDate=$sdkReleaseDate",
                )
            }
        }

        // 10. 能力授权。当前 license 只按 ASR / TTS 两类授权，不再细分语言或增强能力。
        val normalizedFeatures = claims.features.map { it.trim().uppercase(Locale.ROOT) }.toSet()
        if (!normalizedFeatures.contains(requiredFeature.uppercase(Locale.ROOT))) {
            return failWith(
                claims,
                TtsErrorCode.LICENSE_FEATURE_MISSING,
                "license features=${claims.features.joinToString(",")} missing $requiredFeature",
            )
        }

        // 11. SN 白名单绑定。新 license 使用 authorizedDeviceHashes；旧 deviceSha256 仅保留兼容。
        if (claims.authorizedDeviceHashes.isNotEmpty()) {
            if (!claims.deviceIdHashAlg.equals("SHA-256", ignoreCase = true)) {
                return failWith(claims, TtsErrorCode.LICENSE_MALFORMED, "unsupported deviceIdHashAlg=${claims.deviceIdHashAlg}")
            }
            val have = deviceSerial?.let { DeviceLicenseFingerprint.computeFromSerial(it, claims.deviceIdSaltId) }
                ?: return failWith(claims, TtsErrorCode.LICENSE_DEVICE_MISMATCH, "device SN unavailable")
            if (!claims.authorizedDeviceHashes.contains(have)) {
                return failWith(
                    claims,
                    TtsErrorCode.LICENSE_DEVICE_MISMATCH,
                    "device hash not authorized",
                )
            }
        } else if (claims.deviceSha256.isNotBlank()) {
            val have = deviceSerial?.let { DeviceLicenseFingerprint.computeFromSerial(it, claims.deviceIdSaltId) }
                ?: return failWith(claims, TtsErrorCode.LICENSE_DEVICE_MISMATCH, "device SN unavailable")
            if (normalizeHex(claims.deviceSha256) != have) {
                return failWith(claims, TtsErrorCode.LICENSE_DEVICE_MISMATCH, "legacy device hash mismatch")
            }
        }

        // 全部通过。
        return Result(
            TtsLicenseStatus(
                state = TtsLicenseStatus.State.LICENSED,
                valid = true,
                errorCode = TtsErrorCode.OK,
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
            TtsErrorCode.OK,
            null,
        )
    }

    /** 未武装 / 无 Context 时的开发态结果（放行）。 */
    internal fun devResult(packageName: String): Result = Result(dev(packageName), TtsErrorCode.OK, null)

    // -------- 内部 --------

    private fun parseClaims(payloadJson: String): LicenseClaims {
        val o = JSONObject(payloadJson)
        return LicenseClaims(
            licenseId = o.optString("licenseId", ""),
            customer = o.optString("customer", ""),
            applicationId = o.optString("applicationId", ""),
            bundleName = o.optString("bundleName", ""),
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

    private fun dev(pkg: String): TtsLicenseStatus = TtsLicenseStatus(
        state = TtsLicenseStatus.State.DEV_UNLICENSED,
        valid = false,
        errorCode = TtsErrorCode.OK,
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
        TtsLicenseStatus(
            state = TtsLicenseStatus.State.INVALID,
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
        TtsLicenseStatus(
            state = TtsLicenseStatus.State.INVALID,
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
