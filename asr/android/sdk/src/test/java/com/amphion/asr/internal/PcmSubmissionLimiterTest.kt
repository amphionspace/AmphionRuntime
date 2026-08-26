package com.amphion.asr.internal

import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PcmSubmissionLimiterTest {
    @Test
    fun fullBudgetBlocksUntilSamplesAreReleased() {
        val limiter = PcmSubmissionLimiter(10)
        assertTrue(limiter.reserve(10))
        val entered = CountDownLatch(1)
        val returned = CountDownLatch(1)
        var accepted = false
        val thread = Thread {
            entered.countDown()
            accepted = limiter.reserve(1)
            returned.countDown()
        }.apply { start() }

        assertTrue(entered.await(1, TimeUnit.SECONDS))
        assertFalse(returned.await(100, TimeUnit.MILLISECONDS))
        limiter.release(1)
        assertTrue(returned.await(1, TimeUnit.SECONDS))
        assertTrue(accepted)
        thread.join()
    }

    @Test
    fun stopAcceptingWakesBlockedProducerWithoutReservation() {
        val limiter = PcmSubmissionLimiter(10)
        assertTrue(limiter.reserve(10))
        val returned = CountDownLatch(1)
        var accepted = true
        val thread = Thread {
            accepted = limiter.reserve(1)
            returned.countDown()
        }.apply { start() }

        assertFalse(returned.await(100, TimeUnit.MILLISECONDS))
        limiter.stopAccepting()
        assertTrue(returned.await(1, TimeUnit.SECONDS))
        assertFalse(accepted)
        thread.join()
    }
}
