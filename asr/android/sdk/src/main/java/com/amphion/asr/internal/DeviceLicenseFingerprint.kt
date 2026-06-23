package com.amphion.asr.internal

import android.content.Context
import android.provider.Settings
import java.security.MessageDigest
import java.util.Locale

/**
 * 离线 license 单机绑定用的设备指纹。
 *
 * 算法：SHA-256( UTF-8("{applicationId}|{ANDROID_ID}") )，大写 hex、无冒号。
 * 与签发端 `asr/tools/license/issue_license.py --device-sha256` 一致。
 *
 * 不采集 IMEI/MAC；ANDROID_ID 在恢复出厂设置后可能变化。
 */
internal object DeviceLicenseFingerprint {

    fun compute(ctx: Context): String {
        val pkg = ctx.packageName ?: ""
        val androidId = Settings.Secure.getString(ctx.contentResolver, Settings.Secure.ANDROID_ID) ?: ""
        val raw = "$pkg|$androidId"
        return sha256HexNoColon(raw.toByteArray(Charsets.UTF_8))
    }

    internal fun sha256HexNoColon(bytes: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
        val sb = StringBuilder(digest.size * 2)
        for (b in digest) sb.append(String.format(Locale.ROOT, "%02X", b.toInt() and 0xFF))
        return sb.toString()
    }
}
