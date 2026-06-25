package com.amphion.asr.internal

import android.content.Context
import com.amphion.asr.AmphionDeviceIdProvider
import java.security.MessageDigest
import java.util.Locale

/**
 * 离线 license 设备白名单绑定用的 SN 哈希。
 *
 * 算法：SHA-256( UTF-8(normalizedSn + deviceIdSaltId) )，大写 hex、无冒号。
 * 与签发端 `tools/license/issue_license.py --device-id-file ... --device-id-salt-id ...` 一致。
 *
 * SDK 不直接保存明文 SN 清单；SN 来源由客户或交付适配层通过 [AmphionDeviceIdProvider] 注入。
 */
internal object DeviceLicenseFingerprint {

    fun compute(ctx: Context, provider: AmphionDeviceIdProvider?, saltId: String): String? {
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

    internal fun sha256HexNoColon(bytes: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
        val sb = StringBuilder(digest.size * 2)
        for (b in digest) sb.append(String.format(Locale.ROOT, "%02X", b.toInt() and 0xFF))
        return sb.toString()
    }
}
