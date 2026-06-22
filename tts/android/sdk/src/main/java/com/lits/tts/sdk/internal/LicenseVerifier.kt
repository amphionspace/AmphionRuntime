package com.lits.tts.sdk.internal

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.provider.Settings
import android.util.Base64
import com.lits.tts.sdk.TtsErrorCode
import com.lits.tts.sdk.TtsLicenseStatus
import java.security.KeyFactory
import java.security.MessageDigest
import java.security.Signature
import java.security.spec.X509EncodedKeySpec
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone
import org.json.JSONObject

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
        nowMillis: Long = System.currentTimeMillis(),
    ): Result {
        val packageName = ctx.packageName.orEmpty()
        if (publicKeyB64.isBlank()) {
            return Result(dev(packageName), TtsErrorCode.OK, null)
        }
        if (licenseText.isNullOrBlank()) {
            return fail(packageName, TtsErrorCode.LICENSE_MISSING, "no license provided")
        }

        val payloadBytes: ByteArray
        val signatureBytes: ByteArray
        try {
            val envelope = JSONObject(licenseText)
            payloadBytes = Base64.decode(envelope.getString("payload_b64"), Base64.NO_WRAP)
            signatureBytes = Base64.decode(envelope.getString("sig_b64"), Base64.NO_WRAP)
        } catch (error: Throwable) {
            return fail(packageName, TtsErrorCode.LICENSE_MALFORMED, "bad envelope: ${error.message}")
        }

        val claims = try {
            parseClaims(String(payloadBytes, Charsets.UTF_8))
        } catch (error: Throwable) {
            return fail(packageName, TtsErrorCode.LICENSE_MALFORMED, "bad payload: ${error.message}")
        }

        val signatureValid = try {
            val keyBytes = Base64.decode(publicKeyB64, Base64.NO_WRAP)
            val publicKey = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(keyBytes))
            Signature.getInstance("SHA256withECDSA").run {
                initVerify(publicKey)
                update(payloadBytes)
                verify(signatureBytes)
            }
        } catch (error: Throwable) {
            return failWith(claims, TtsErrorCode.LICENSE_SIGNATURE_INVALID, "verify error: ${error.message}")
        }
        if (!signatureValid) {
            return failWith(claims, TtsErrorCode.LICENSE_SIGNATURE_INVALID, "signature mismatch")
        }

        if (claims.applicationId != packageName) {
            return failWith(
                claims,
                TtsErrorCode.LICENSE_APP_MISMATCH,
                "license app=${claims.applicationId} host=$packageName",
            )
        }

        if (claims.certSha256.isNotBlank()) {
            val expected = normalizeHex(claims.certSha256)
            val actual = hostCertSha256Set(ctx)
            if (!actual.contains(expected)) {
                return failWith(
                    claims,
                    TtsErrorCode.LICENSE_CERT_MISMATCH,
                    "license cert=$expected host=${actual.joinToString(",")}",
                )
            }
        }

        if (claims.expiresAt.isNotBlank()) {
            val expiresAt = parseDateUtcMillis(claims.expiresAt)
                ?: return failWith(claims, TtsErrorCode.LICENSE_MALFORMED, "bad expiresAt=${claims.expiresAt}")
            val deadline = expiresAt + (expiryGraceDays + 1).toLong() * DAY_MS
            if (nowMillis >= deadline) {
                return failWith(claims, TtsErrorCode.LICENSE_EXPIRED, "expiresAt=${claims.expiresAt}")
            }
        }

        if (claims.deviceSha256.isNotBlank()) {
            val expected = normalizeHex(claims.deviceSha256)
            val actual = deviceFingerprint(ctx)
            if (expected != actual) {
                return failWith(claims, TtsErrorCode.LICENSE_DEVICE_MISMATCH, "license device=$expected host=$actual")
            }
        }

        return Result(
            TtsLicenseStatus(
                state = TtsLicenseStatus.State.LICENSED,
                valid = true,
                errorCode = TtsErrorCode.OK,
                licenseId = claims.licenseId,
                customer = claims.customer,
                applicationId = claims.applicationId,
                issuedAt = claims.issuedAt,
                expiresAt = claims.expiresAt,
                installTier = claims.installTier,
                features = claims.features,
            ),
            TtsErrorCode.OK,
            null,
        )
    }

    fun deviceFingerprint(ctx: Context): String {
        val androidId = Settings.Secure.getString(ctx.contentResolver, Settings.Secure.ANDROID_ID).orEmpty()
        return sha256HexNoColon("${ctx.packageName}|$androidId".toByteArray(Charsets.UTF_8))
    }

    private fun parseClaims(payloadJson: String): LicenseClaims {
        val payload = JSONObject(payloadJson)
        val featuresJson = payload.optJSONArray("features")
        val features = if (featuresJson == null) {
            emptyList()
        } else {
            (0 until featuresJson.length()).map { featuresJson.getString(it) }
        }
        return LicenseClaims(
            licenseId = payload.optString("licenseId", ""),
            customer = payload.optString("customer", ""),
            applicationId = payload.getString("applicationId"),
            certSha256 = payload.optString("certSha256", ""),
            deviceSha256 = payload.optString("deviceSha256", ""),
            issuedAt = payload.optString("issuedAt", ""),
            expiresAt = payload.optString("expiresAt", ""),
            installTier = payload.optString("installTier", ""),
            features = features,
            sdkMajor = payload.optInt("sdkMajor", -1),
        )
    }

    private fun hostCertSha256Set(ctx: Context): Set<String> {
        val signatures: Array<android.content.pm.Signature> = try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                val info = ctx.packageManager.getPackageInfo(ctx.packageName, PackageManager.GET_SIGNING_CERTIFICATES)
                val signingInfo = info.signingInfo
                when {
                    signingInfo == null -> emptyArray()
                    signingInfo.hasMultipleSigners() -> signingInfo.apkContentsSigners
                    else -> signingInfo.signingCertificateHistory ?: signingInfo.apkContentsSigners
                }
            } else {
                @Suppress("DEPRECATION")
                ctx.packageManager.getPackageInfo(ctx.packageName, PackageManager.GET_SIGNATURES).signatures ?: emptyArray()
            }
        } catch (_: Throwable) {
            emptyArray()
        }
        return signatures.mapNotNull { signature ->
            runCatching { sha256HexNoColon(signature.toByteArray()) }.getOrNull()
        }.toSet()
    }

    private fun parseDateUtcMillis(value: String): Long? = try {
        SimpleDateFormat("yyyy-MM-dd", Locale.ROOT).apply {
            timeZone = TimeZone.getTimeZone("UTC")
            isLenient = false
        }.parse(value)?.time
    } catch (_: Throwable) {
        null
    }

    private fun normalizeHex(value: String): String =
        value.replace(":", "").replace(" ", "").uppercase(Locale.ROOT)

    private fun sha256HexNoColon(bytes: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
        return buildString(digest.size * 2) {
            for (byte in digest) {
                append(String.format(Locale.ROOT, "%02X", byte.toInt() and 0xFF))
            }
        }
    }

    private fun dev(packageName: String): TtsLicenseStatus = TtsLicenseStatus(
        state = TtsLicenseStatus.State.DEV_UNLICENSED,
        valid = false,
        errorCode = TtsErrorCode.OK,
        licenseId = "",
        customer = "",
        applicationId = packageName,
        issuedAt = "",
        expiresAt = "",
        installTier = "",
        features = emptyList(),
    )

    private fun fail(packageName: String, code: Int, message: String): Result = Result(
        TtsLicenseStatus(
            state = TtsLicenseStatus.State.INVALID,
            valid = false,
            errorCode = code,
            licenseId = "",
            customer = "",
            applicationId = packageName,
            issuedAt = "",
            expiresAt = "",
            installTier = "",
            features = emptyList(),
        ),
        code,
        message,
    )

    private fun failWith(claims: LicenseClaims, code: Int, message: String): Result = Result(
        TtsLicenseStatus(
            state = TtsLicenseStatus.State.INVALID,
            valid = false,
            errorCode = code,
            licenseId = claims.licenseId,
            customer = claims.customer,
            applicationId = claims.applicationId,
            issuedAt = claims.issuedAt,
            expiresAt = claims.expiresAt,
            installTier = claims.installTier,
            features = claims.features,
        ),
        code,
        message,
    )
}
