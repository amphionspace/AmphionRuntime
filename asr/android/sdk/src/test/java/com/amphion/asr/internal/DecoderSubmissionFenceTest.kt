package com.amphion.asr.internal

import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DecoderSubmissionFenceTest {

    @Test
    fun acceptedAudioIsEnqueuedBeforeConcurrentStopAndLateAudioIsRejected() {
        val fence = DecoderSubmissionFence()
        val order = Collections.synchronizedList(mutableListOf<String>())
        val audioEntered = CountDownLatch(1)
        val releaseAudio = CountDownLatch(1)

        val audio = thread {
            assertTrue(fence.submitActive {
                audioEntered.countDown()
                assertTrue(releaseAudio.await(2, TimeUnit.SECONDS))
                order += "audio"
            })
        }
        assertTrue(audioEntered.await(2, TimeUnit.SECONDS))
        val stop = thread {
            assertTrue(fence.submitStop { order += "stop" })
        }

        releaseAudio.countDown()
        audio.join(2_000)
        stop.join(2_000)

        assertEquals(listOf("audio", "stop"), order)
        assertFalse(fence.submitActive { order += "late-audio" })
        assertFalse(fence.submitStop { order += "duplicate-stop" })
    }

    @Test
    fun closeIsAllowedAfterStopButRejectsEveryLaterSubmission() {
        val fence = DecoderSubmissionFence()

        assertTrue(fence.submitStop {})
        assertTrue(fence.submitClose {})
        assertFalse(fence.submitActive {})
        assertFalse(fence.submitStop {})
        assertFalse(fence.submitClose {})
    }
}
