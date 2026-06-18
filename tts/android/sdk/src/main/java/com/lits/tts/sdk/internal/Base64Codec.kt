package com.lits.tts.sdk.internal

import java.io.ByteArrayOutputStream

/**
 * 标准 RFC 4648 base64 解码器（标准字母表 `+/`，带/不带 padding 均可，忽略换行/空白）。
 *
 * 为什么 SDK 自带而不用平台 API（第一性原理）：
 * - `java.util.Base64` 需 API 26，但本 SDK `minSdk=24`，不可用；
 * - `android.util.Base64` 在纯 JVM 单元测试里是会抛异常的桩，验签逻辑无法离设备自测；
 * - base64 是确定性、可逐字节复核的编码（非密码学原语），自带一份既覆盖 API 24+ 又可测。
 *
 * 仅 SDK 内部使用。SDK 运行时只需要解码（解 `payload_b64` / `sig_b64` / 公钥）。
 */
internal object Base64Codec {

    private val DECODE_TABLE: IntArray = IntArray(128) { -1 }.also { table ->
        val alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        for (i in alphabet.indices) {
            table[alphabet[i].code] = i
        }
    }

    fun decode(input: String): ByteArray {
        val out = ByteArrayOutputStream(input.length * 3 / 4 + 3)
        var buffer = 0
        var bitsCollected = 0
        for (ch in input) {
            if (ch == '=' || ch == '\n' || ch == '\r' || ch == ' ' || ch == '\t') continue
            val code = ch.code
            val value = if (code in 0..127) DECODE_TABLE[code] else -1
            require(value >= 0) { "illegal base64 character: '$ch'" }
            buffer = (buffer shl 6) or value
            bitsCollected += 6
            if (bitsCollected >= 8) {
                bitsCollected -= 8
                out.write((buffer shr bitsCollected) and 0xFF)
            }
        }
        return out.toByteArray()
    }
}
