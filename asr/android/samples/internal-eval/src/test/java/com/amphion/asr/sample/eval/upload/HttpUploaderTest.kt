package com.amphion.asr.sample.eval.upload

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * HttpUploader.classify 的单测。
 *
 * 只测分类逻辑（companion 静态纯函数），不发真实 HTTP；网络层留给手测 / instrumented test。
 *
 * 关键回归点（来自历史 bug）：
 * - HTTP 429 RATE_LIMITED 必须归 Retry，不能归 Failure（否则连发录音被永久丢弃）
 */
class HttpUploaderTest {

    @Test fun `200 stored is success not duplicate`() {
        val r = HttpUploader.classify(200, """{"status":"stored","recording_id":"x"}""")
        assertTrue(r is HttpUploader.Result.Success)
        assertEquals(false, (r as HttpUploader.Result.Success).duplicate)
    }

    @Test fun `200 duplicate marked as duplicate`() {
        val r = HttpUploader.classify(200, """{"status":"duplicate","recording_id":"x"}""")
        assertTrue(r is HttpUploader.Result.Success)
        assertEquals(true, (r as HttpUploader.Result.Success).duplicate)
    }

    @Test fun `200 empty body still success`() {
        val r = HttpUploader.classify(200, "")
        assertTrue(r is HttpUploader.Result.Success)
    }

    @Test fun `401 unauthorized is permanent failure`() {
        val r = HttpUploader.classify(401, """{"code":"UNAUTHORIZED","message":"bad token"}""")
        assertTrue(r is HttpUploader.Result.Failure)
        assertEquals("UNAUTHORIZED", (r as HttpUploader.Result.Failure).errorCode)
    }

    @Test fun `403 forbidden is permanent failure`() {
        val r = HttpUploader.classify(403, """{"code":"FORBIDDEN","message":"tester mismatch"}""")
        assertTrue(r is HttpUploader.Result.Failure)
    }

    @Test fun `413 payload too large is permanent`() {
        val r = HttpUploader.classify(413, """{"code":"PAYLOAD_TOO_LARGE"}""")
        assertTrue(r is HttpUploader.Result.Failure)
    }

    @Test fun `415 unsupported media type is permanent`() {
        val r = HttpUploader.classify(415, """{"code":"UNSUPPORTED_MEDIA_TYPE"}""")
        assertTrue(r is HttpUploader.Result.Failure)
    }

    @Test fun `400 schema mismatch is permanent`() {
        val r = HttpUploader.classify(400, """{"code":"SCHEMA_MISMATCH","message":"v2"}""")
        assertTrue(r is HttpUploader.Result.Failure)
    }

    @Test fun `400 invalid audio is permanent`() {
        val r = HttpUploader.classify(400, """{"code":"INVALID_AUDIO"}""")
        assertTrue(r is HttpUploader.Result.Failure)
    }

    @Test fun `400 recording id mismatch is permanent`() {
        val r = HttpUploader.classify(400, """{"code":"RECORDING_ID_MISMATCH"}""")
        assertTrue(r is HttpUploader.Result.Failure)
    }

    /**
     * REGRESSION: 历史上把所有 4xx 一律归 Failure，导致连发录音撞 429 后永久丢弃。
     * 必须保持 RATE_LIMITED 归 Retry。
     */
    @Test fun `429 rate limited is RETRY not failure`() {
        val r = HttpUploader.classify(429, """{"code":"RATE_LIMITED","message":"slow down"}""")
        assertTrue("expected Retry but got $r", r is HttpUploader.Result.Retry)
    }

    @Test fun `4xx with unknown body code falls back to retry`() {
        // 服务端返回了一个新错误码我们还不认识 —— 保守按 Retry 处理，避免误丢数据
        val r = HttpUploader.classify(418, """{"code":"BREW_COFFEE"}""")
        assertTrue(r is HttpUploader.Result.Retry)
    }

    @Test fun `401 with empty body still permanent via http code fallback`() {
        val r = HttpUploader.classify(401, "")
        assertTrue(r is HttpUploader.Result.Failure)
        assertEquals("UNAUTHORIZED", (r as HttpUploader.Result.Failure).errorCode)
    }

    @Test fun `500 server error is retry`() {
        val r = HttpUploader.classify(500, """{"code":"INTERNAL","message":"oops"}""")
        assertTrue(r is HttpUploader.Result.Retry)
    }

    @Test fun `503 storage full is retry`() {
        val r = HttpUploader.classify(503, """{"code":"STORAGE_FULL"}""")
        assertTrue(r is HttpUploader.Result.Retry)
    }

    @Test fun `1xx info is retry`() {
        val r = HttpUploader.classify(199, "{}")
        assertTrue(r is HttpUploader.Result.Retry)
    }

    @Test fun `permanent codes set covers spec list`() {
        val expected = setOf(
            "SCHEMA_MISMATCH",
            "INVALID_AUDIO",
            "RECORDING_ID_MISMATCH",
            "UNAUTHORIZED",
            "FORBIDDEN",
            "PAYLOAD_TOO_LARGE",
            "UNSUPPORTED_MEDIA_TYPE",
        )
        assertEquals(expected, HttpUploader.PERMANENT_CODES)
    }

    @Test fun `failure message non-empty for spec error`() {
        val r = HttpUploader.classify(401, """{"code":"UNAUTHORIZED","message":"bad token"}""")
        val f = r as HttpUploader.Result.Failure
        assertNotNull(f.message)
        assertTrue(f.message.isNotBlank())
    }
}
