package com.amphion.asr.internal

import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ClosingSessionBarrierTest {

    @Test
    fun nextSessionWaitsForEveryTrackedDecoderToBecomeQuiescent() {
        val firstReleased = CountDownLatch(1)
        val secondReleased = CountDownLatch(1)
        val barrier = ClosingSessionBarrier<String>(
            awaitQuiescent = { value, timeoutMs ->
                when (value) {
                    "first" -> firstReleased.await(timeoutMs, TimeUnit.MILLISECONDS)
                    else -> secondReleased.await(timeoutMs, TimeUnit.MILLISECONDS)
                }
            },
            monotonicMs = { System.nanoTime() / 1_000_000L },
        )
        barrier.track("first")
        barrier.track("second")

        val finished = CountDownLatch(1)
        thread {
            assertTrue(barrier.awaitAll(2_000))
            finished.countDown()
        }

        assertFalse(finished.await(50, TimeUnit.MILLISECONDS))
        firstReleased.countDown()
        assertFalse(finished.await(50, TimeUnit.MILLISECONDS))
        secondReleased.countDown()
        assertTrue(finished.await(2, TimeUnit.SECONDS))
        assertTrue(barrier.awaitAll(0))
    }

    @Test
    fun timeoutKeepsSessionTrackedForALaterRetry() {
        var canClose = false
        var now = 100L
        val barrier = ClosingSessionBarrier<String>(
            awaitQuiescent = { _, _ -> canClose },
            monotonicMs = { now++ },
        )
        barrier.track("session")

        assertFalse(barrier.awaitAll(10))
        canClose = true
        assertTrue(barrier.awaitAll(10))
        assertTrue(barrier.awaitAll(0))
    }
}
