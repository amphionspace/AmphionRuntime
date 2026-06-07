package com.amphion.asr.internal

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.util.Base64
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
     * @param publicKeyB64 构建期注入的 X.509 SubjectPublicKeyInfo（DER）的 base64；
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
        nowMillis: Long = System.currentTimeMillis(),
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
        val signatureValid: Boolean = try {
            val keyBytes = Base64.decode(publicKeyB64, Base64.NO_WRAP)
            val pub = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(keyBytes))
            Signature.getInstance("SHA256withECDSA").run {
                initVerify(pub)
                update(payloadBytes)
                verify(sigBytes)
            }
        } catch (t: Throwable) {
            return failWith(claims, AsrErrorCode.LICENSE_SIGNATURE_INVALID, "verify error: ${t.message}")
        }
        if (!signatureValid) {
            return failWith(claims, AsrErrorCode.LICENSE_SIGNATURE_INVALID, "signature mismatch")
        }

        // 6. applicationId 绑定。
        if (claims.applicationId != pkg) {
            return failWith(
                claims,
                AsrErrorCode.LICENSE_APP_MISMATCH,
                "license app=${claims.applicationId} host=$pkg",
            )
        }

        // 7. 签名证书绑定（certSha256 非空时才校验）。
        if (claims.certSha256.isNotBlank()) {
            val want = normalizeCert(claims.certSha256)
            val have = hostCertSha256Set(ctx)
            if (!have.contains(want)) {
                return failWith(
                    claims,
                    AsrErrorCode.LICENSE_CERT_MISMATCH,
                    "license cert=$want host=${have.joinToString(",")}",
                )
            }
        }

        // 8. 到期校验（expiresAt 非空时才校验；到期日当天有效，再加宽限）。
        if (claims.expiresAt.isNotBlank()) {
            val expMillis = parseDateUtcMillis(claims.expiresAt)
                ?: return failWith(claims, AsrErrorCode.LICENSE_MALFORMED, "bad expiresAt=${claims.expiresAt}")
            val deadline = expMillis + (expiryGraceDays + 1).toLong() * DAY_MS
            if (nowMillis >= deadline) {
                return failWith(claims, AsrErrorCode.LICENSE_EXPIRED, "expiresAt=${claims.expiresAt}")
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
                applicationId = claims.applicationId,
                issuedAt = claims.issuedAt,
                expiresAt = claims.expiresAt,
                installTier = claims.installTier,
                features = claims.features,
            ),
            AsrErrorCode.OK,
            null,
        )
    }

    // -------- 内部 --------

    private fun parseClaims(payloadJson: String): LicenseClaims {
        val o = JSONObject(payloadJson)
        val arr = o.optJSONArray("features")
        val features = if (arr == null) emptyList() else (0 until arr.length()).map { arr.getString(it) }
        return LicenseClaims(
            licenseId = o.optString("licenseId", ""),
            customer = o.optString("customer", ""),
            applicationId = o.getString("applicationId"),
            certSha256 = o.optString("certSha256", ""),
            issuedAt = o.optString("issuedAt", ""),
            expiresAt = o.optString("expiresAt", ""),
            installTier = o.optString("installTier", ""),
            features = features,
            sdkMajor = o.optInt("sdkMajor", -1),
        )
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

    private fun normalizeCert(s: String): String =
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
            applicationId = claims.applicationId,
            issuedAt = claims.issuedAt,
            expiresAt = claims.expiresAt,
            installTier = claims.installTier,
            features = claims.features,
        ),
        code,
        msg,
    )
}
