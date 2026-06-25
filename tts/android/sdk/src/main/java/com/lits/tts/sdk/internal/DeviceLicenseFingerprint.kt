package com.lits.tts.sdk.internal

import android.content.Context
import android.provider.Settings
import com.lits.tts.sdk.TtsDeviceIdProvider
import java.security.MessageDigest
import java.util.Locale

/**
 * 离线 license 设备白名单绑定用的 SN 哈希。
 *
 * 新 Dingqiao license 算法：SHA-256( UTF-8(normalizedSn + deviceIdSaltId) )，大写 hex、无冒号。
 */
internal object DeviceLicenseFingerprint {

    fun compute(ctx: Context, provider: TtsDeviceIdProvider?, saltId: String): String? {
        val sn = provider?.getDeviceSerial(ctx)?.let(::normalizeDeviceId)
        if (sn.isNullOrBlank()) return null
        return computeFromSerial(sn, saltId)
    }

    fun computeFromSerial(deviceSerial: String, saltId: String): String {
        val raw = normalizeDeviceId(deviceSerial) + saltId
        return sha256HexNoColon(raw.toByteArray(Charsets.UTF_8))
    }

    fun normalizeDeviceId(value: String): String =
        value.trim().uppercase(Locale.ROOT)

    /**
     * Legacy helper kept for old app code that explicitly passes Android ID style device codes.
     */
    fun compute(ctx: Context): String {
        val pkg = ctx.packageName ?: ""
        val androidId = Settings.Secure.getString(ctx.contentResolver, Settings.Secure.ANDROID_ID) ?: ""
        return compute(pkg, androidId)
    }

    fun compute(applicationId: String, deviceCode: String): String {
        val raw = "${applicationId.trim()}|${deviceCode.trim()}"
        return sha256HexNoColon(raw.toByteArray(Charsets.UTF_8))
    }

    internal fun sha256HexNoColon(bytes: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
        val sb = StringBuilder(digest.size * 2)
        for (b in digest) sb.append(String.format(Locale.ROOT, "%02X", b.toInt() and 0xFF))
        return sb.toString()
    }
}
