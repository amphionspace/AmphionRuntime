package com.amphion.asr.sample.eval.upload

import com.amphion.asr.sample.eval.model.DeviceMeta
import com.amphion.asr.sample.eval.model.EnvMeta
import com.amphion.asr.sample.eval.model.RecordingMeta
import com.amphion.asr.sample.eval.model.UploadMeta
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

/**
 * UploadScanner.backoffMs / shouldRetryNow 的单测。
 *
 * 退避表（无 jitter 时）：
 * - attempts=1 → 2s
 * - attempts=2 → 4s
 * - attempts=3 → 8s
 * - attempts=4 → 16s
 * - attempts=8 → 256s（256_000ms）
 * - attempts>=9 → 300s（5min 上限）
 *
 * Jitter 不可去掉，但用 fixed seed 让结果可重现。
 */
class UploadScannerBackoffTest {

    /** 关闭 jitter（取 jitter 中位数 1.0）：fix random 给固定 0.5 */
    private val midRandom = object : Random() {
        override fun nextBits(bitCount: Int): Int = 0
        override fun nextDouble(): Double = 0.5
    }

    @Test fun `backoff first attempt is base`() {
        // 1 attempt: base * factor^0 = 2000ms; jitter ratio 0 (random.nextDouble()=0.5 → 1.0)
        assertEquals(2_000L, UploadScanner.backoffMs(1, midRandom))
    }

    @Test fun `backoff doubles each attempt`() {
        assertEquals(2_000L, UploadScanner.backoffMs(1, midRandom))
        assertEquals(4_000L, UploadScanner.backoffMs(2, midRandom))
        assertEquals(8_000L, UploadScanner.backoffMs(3, midRandom))
        assertEquals(16_000L, UploadScanner.backoffMs(4, midRandom))
        assertEquals(32_000L, UploadScanner.backoffMs(5, midRandom))
    }

    @Test fun `backoff capped at 5 minutes`() {
        // attempts=9 → raw = 2 * 2^8 = 512s; capped at 300s
        assertEquals(300_000L, UploadScanner.backoffMs(9, midRandom))
        assertEquals(300_000L, UploadScanner.backoffMs(20, midRandom))
        assertEquals(300_000L, UploadScanner.backoffMs(100, midRandom))
    }

    @Test fun `backoff handles zero or negative attempts as one`() {
        assertEquals(2_000L, UploadScanner.backoffMs(0, midRandom))
        assertEquals(2_000L, UploadScanner.backoffMs(-5, midRandom))
    }

    @Test fun `backoff jitter stays within 20 percent`() {
        // 默认 Random 跑多次都应该落在 [0.8x, 1.2x] 区间
        val base = 16_000L
        val expectedMin = (base * 0.8).toLong()
        val expectedMax = (base * 1.2).toLong()
        repeat(200) {
            val v = UploadScanner.backoffMs(4)
            assertTrue("$v not in [$expectedMin,$expectedMax]", v in expectedMin..expectedMax)
        }
    }

    @Test fun `pending always allowed regardless of clock`() {
        val meta = stubMeta(attempts = 0, lastAttemptAt = null, state = UploadMeta.State.PENDING)
        assertTrue(UploadScanner.shouldRetryNow(meta, 0L))
        assertTrue(UploadScanner.shouldRetryNow(meta, Long.MAX_VALUE))
    }

    @Test fun `retry within backoff window blocked`() {
        val attempts = 3 // backoff ~ 8s
        val lastMs = 1_000_000_000L
        val meta = stubMeta(
            attempts = attempts,
            lastAttemptAt = isoOf(lastMs),
            state = UploadMeta.State.RETRY,
        )
        // 4 秒后未到 8s 阈值
        assertFalse(UploadScanner.shouldRetryNow(meta, lastMs + 4_000L))
    }

    @Test fun `retry after backoff window allowed`() {
        val attempts = 3
        val lastMs = 1_000_000_000L
        val meta = stubMeta(
            attempts = attempts,
            lastAttemptAt = isoOf(lastMs),
            state = UploadMeta.State.RETRY,
        )
        // 12 秒后远超 8s+jitter 阈值
        assertTrue(UploadScanner.shouldRetryNow(meta, lastMs + 12_000L))
    }

    @Test fun `retry with missing lastAttemptAt falls through to allowed`() {
        // attempts>0 但 lastAttemptAt 缺失：保守 true，避免老 meta 永不重传
        val meta = stubMeta(
            attempts = 5,
            lastAttemptAt = null,
            state = UploadMeta.State.RETRY,
        )
        assertTrue(UploadScanner.shouldRetryNow(meta, 0L))
    }

    @Test fun `retry with malformed lastAttemptAt falls through to allowed`() {
        val meta = stubMeta(
            attempts = 5,
            lastAttemptAt = "not-an-iso",
            state = UploadMeta.State.RETRY,
        )
        assertTrue(UploadScanner.shouldRetryNow(meta, 0L))
    }

    // -------- helpers --------

    private fun isoOf(millis: Long): String {
        val fmt = java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", java.util.Locale.US)
        fmt.timeZone = java.util.TimeZone.getTimeZone("UTC")
        return fmt.format(java.util.Date(millis))
    }

    private fun stubMeta(attempts: Int, lastAttemptAt: String?, state: String): RecordingMeta =
        RecordingMeta(
            finalized = true,
            recordingId = "rid-test",
            attemptIndex = 1,
            sentenceId = "sent-test",
            categoryId = "cat",
            referenceText = "hello",
            testerId = "tester1",
            testerNickname = "Tester1",
            device = DeviceMeta(model = "x", manufacturer = "y", androidSdk = 34, abi = "arm64-v8a"),
            appVersion = "0.0.0",
            sdkVersion = "0.0.0",
            modelId = null,
            modelVersion = null,
            recordedAt = "2026-05-19T00:00:00Z",
            durationMs = 1000,
            sampleRate = 16000,
            gainDb = 0f,
            audioSource = "MIC",
            env = EnvMeta(location = "", noiseLevel = "low", noiseLevelDbEstimate = null, notes = ""),
            onDeviceHypothesis = null,
            onDeviceWerEstimate = null,
            upload = UploadMeta(
                state = state,
                attempts = attempts,
                lastAttemptAt = lastAttemptAt,
            ),
        )
}
