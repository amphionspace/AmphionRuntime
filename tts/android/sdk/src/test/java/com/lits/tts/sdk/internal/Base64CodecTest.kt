package com.lits.tts.sdk.internal

import java.util.Base64
import kotlin.random.Random
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 验证内部 [Base64Codec.decode] 与 JDK 标准 base64 逐字节一致——SDK 端验签依赖它解码
 * 签发端（Python `base64.b64encode`，标准字母表）产出的 `payload_b64` / `sig_b64`。
 */
class Base64CodecTest {

    @Test
    fun decodesKnownVectors() {
        assertArrayEquals("Man".toByteArray(Charsets.UTF_8), Base64Codec.decode("TWFu"))
        assertArrayEquals("Ma".toByteArray(Charsets.UTF_8), Base64Codec.decode("TWE="))
        assertArrayEquals("M".toByteArray(Charsets.UTF_8), Base64Codec.decode("TQ=="))
        assertArrayEquals(ByteArray(0), Base64Codec.decode(""))
    }

    @Test
    fun matchesJdkEncoderForRandomPayloads() {
        val encoder = Base64.getEncoder()
        repeat(500) { i ->
            val data = Random.nextBytes(i % 257)
            val b64 = encoder.encodeToString(data)
            assertArrayEquals(data, Base64Codec.decode(b64))
        }
    }

    @Test
    fun toleratesEmbeddedNewlinesAndWhitespace() {
        val data = Random.nextBytes(96)
        val b64 = Base64.getMimeEncoder().encodeToString(data) // 含 \r\n 折行
        assertArrayEquals(data, Base64Codec.decode(b64))
    }

    @Test
    fun rejectsIllegalCharacter() {
        val error = runCatching { Base64Codec.decode("not*base64") }.exceptionOrNull()
        assertEquals(IllegalArgumentException::class.java, error?.javaClass)
    }
}
