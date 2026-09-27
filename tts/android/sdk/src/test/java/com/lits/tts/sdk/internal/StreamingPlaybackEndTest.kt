package com.lits.tts.sdk.internal

import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import org.junit.Assert.*
import org.junit.Test

class StreamingPlaybackEndTest {
    @Test fun fullQueueDeliversLastAudioBeforeEndSignal() {
        val queue = LinkedBlockingQueue<ByteArray>(1)
        val lastAudio = byteArrayOf(1, 2)
        val end = byteArrayOf()
        val cancelled = AtomicBoolean(false)
        queue.put(lastAudio)
        val producer = Thread { enqueuePlaybackEnd(queue, end, cancelled) }
        producer.start()
        try {
            producer.join(100)
            assertSame(lastAudio, queue.poll(1, TimeUnit.SECONDS))
            assertSame("normal completion must not lose its end signal", end, queue.poll(1, TimeUnit.SECONDS))
            producer.join(1000)
            assertFalse(producer.isAlive)
        } finally { cancelled.set(true); producer.interrupt(); producer.join(1000) }
    }

    @Test fun cancellationReleasesProducerWaitingOnFullQueue() {
        val queue = LinkedBlockingQueue<ByteArray>(1)
        val audio = byteArrayOf(3, 4)
        val cancelled = AtomicBoolean(false)
        queue.put(audio)
        val producer = Thread { enqueuePlaybackEnd(queue, byteArrayOf(), cancelled) }
        producer.start()
        try {
            producer.join(100)
            cancelled.set(true)
            producer.join(1000)
            assertFalse("cancel must not wait for a consumer", producer.isAlive)
            assertSame(audio, queue.poll())
        } finally { producer.interrupt(); producer.join(1000) }
    }
}
