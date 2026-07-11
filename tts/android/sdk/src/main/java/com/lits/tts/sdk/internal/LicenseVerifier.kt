package com.lits.tts.sdk.internal

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import com.lits.tts.sdk.TtsDeviceIdProvider
import com.lits.tts.sdk.TtsErrorCode
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
 */
internal object LicenseVerifier {

    private const val DAY_MS = 24L * 60 * 60 * 1000

    internal class Result(
        val status: TtsLicenseStatus,
        val errorCode: Int,
        val errorMessage: String?,
    ) {
        val ok: Boolean get() = errorCode == TtsErrorCode.OK
    }

    fun verify(
        ctx: Context,
        licenseText: String?,
        publicKeyB64: String,
        expiryGraceDays: Int,
        deviceIdProvider: TtsDeviceIdProvider? = null,
        hostDeviceSha256Override: String? = null,
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
            hostDeviceSha256 = hostDeviceSha256Override?.takeIf { it.isNotBlank() }?.let(::normalizeHex),
            expiryGraceDays = expiryGraceDays,
            sdkMajor = sdkMajor,
            sdkReleaseDate = sdkReleaseDate,
            requiredFeature = requiredFeature,
            nowMillis = nowMillis,
        )
    }

    internal fun verifyResolved(
        licenseText: String?,
        publicKeyB64: String,
        packageName: String,
        hostCertSha256: Set<String>,
        deviceSerial: String?,
        hostDeviceSha256: String? = null,
        expiryGraceDays: Int,
        sdkMajor: Int,
        sdkReleaseDate: String,
        requiredFeature: String,
        nowMillis: Long,
    ): Result {
        if (publicKeyB64.isBlank()) {
            return Result(dev(packageName), TtsErrorCode.OK, null)
        }
        if (licenseText.isNullOrBlank()) {
            return fail(packageName, TtsErrorCode.LICENSE_MISSING, "no license provided")
        }

        val payloadBytes: ByteArray
        val sigBytes: ByteArray
        try {
            val env = JSONObject(licenseText)
            payloadBytes = Base64Codec.decode(env.getString("payload_b64"))
            sigBytes = Base64Codec.decode(env.getString("sig_b64"))
        } catch (t: Throwable) {
            return fail(packageName, TtsErrorCode.LICENSE_MALFORMED, "bad envelope: ${t.message}")
        }

        val claims: LicenseClaims = try {
            parseClaims(String(payloadBytes, Charsets.UTF_8))
        } catch (t: Throwable) {
            return fail(packageName, TtsErrorCode.LICENSE_MALFORMED, "bad payload: ${t.message}")
        }

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

        // 包名绑定：仅当 boundApplicationId 非空时才校验（与下面的 cert / expiry 校验一致，
        // 也与 ASR 验签器一致——ASR 根本不做包名校验）。鼎桥离线 license 按 packageNameBound=false
        // 签发（applicationId/bundleName 均为空），改用 cert + SN 绑定；若在此无条件比对，武装态下
        // 会把这类合法 license 误判为 LICENSE_APP_MISMATCH。
        val boundApp = claims.boundApplicationId
        if (boundApp.isNotBlank() && boundApp != packageName) {
            return failWith(claims, TtsErrorCode.LICENSE_APP_MISMATCH, "license app=$boundApp host=$packageName")
        }

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

        if (claims.expiresAt.isNotBlank()) {
            val expMillis = parseDateUtcMillis(claims.expiresAt)
                ?: return failWith(claims, TtsErrorCode.LICENSE_MALFORMED, "bad expiresAt=${claims.expiresAt}")
            val deadline = expMillis + (expiryGraceDays + 1).toLong() * DAY_MS
            if (nowMillis >= deadline) {
                return failWith(claims, TtsErrorCode.LICENSE_EXPIRED, "expiresAt=${claims.expiresAt}")
            }
        }

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
                ?: return failWith(claims, TtsErrorCode.LICENSE_MALFORMED, "bad maintenanceUntil=${claims.maintenanceUntil}")
            if (releaseMillis > maintenanceMillis) {
                return failWith(
                    claims,
                    TtsErrorCode.LICENSE_MAINTENANCE_EXPIRED,
                    "maintenanceUntil=${claims.maintenanceUntil} sdkReleaseDate=$sdkReleaseDate",
                )
            }
        }

        // 能力授权：无条件校验（与 ASR 验签器一致）。features 为空表示不授权任何能力，必须拒绝——
        // 否则一个空 features 的 license 会绕过能力门禁激活 TTS（与本次鼎桥审计的能力分档诉求相悖）。
        val normalizedFeatures = claims.features.map { it.trim().uppercase(Locale.ROOT) }.toSet()
        if (!normalizedFeatures.contains(requiredFeature.uppercase(Locale.ROOT))) {
            return failWith(
                claims,
                TtsErrorCode.LICENSE_FEATURE_MISSING,
                "license features=${claims.features.joinToString(",")} missing $requiredFeature",
            )
        }

        if (claims.authorizedDeviceHashes.isNotEmpty()) {
            if (!claims.deviceIdHashAlg.equals("SHA-256", ignoreCase = true)) {
                return failWith(claims, TtsErrorCode.LICENSE_MALFORMED, "unsupported deviceIdHashAlg=${claims.deviceIdHashAlg}")
            }
            val have = deviceSerial?.let { DeviceLicenseFingerprint.computeFromSerial(it, claims.deviceIdSaltId) }
                ?: return failWith(claims, TtsErrorCode.LICENSE_DEVICE_MISMATCH, "device SN unavailable")
            if (!claims.authorizedDeviceHashes.contains(have)) {
                return failWith(claims, TtsErrorCode.LICENSE_DEVICE_MISMATCH, "device hash not authorized")
            }
        } else if (claims.deviceSha256.isNotBlank()) {
            val have = when {
                hostDeviceSha256 != null -> hostDeviceSha256
                claims.deviceIdSaltId.isNotBlank() -> deviceSerial?.let {
                    DeviceLicenseFingerprint.computeFromSerial(it, claims.deviceIdSaltId)
                }
                else -> null
            } ?: return failWith(claims, TtsErrorCode.LICENSE_DEVICE_MISMATCH, "device unavailable")
            if (normalizeHex(claims.deviceSha256) != have) {
                return failWith(claims, TtsErrorCode.LICENSE_DEVICE_MISMATCH, "legacy device hash mismatch")
            }
        }

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

    internal fun devResult(packageName: String): Result = Result(dev(packageName), TtsErrorCode.OK, null)

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
