package com.amphion.dingqiao.diarization

import com.amphion.dingqiao.SpeakerDiarizationDegradedReason
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 验证排队与收尾语义，对齐鸿蒙 test_harmony_sortformer_diarization.py 的
 * `test_client_feeds_in_order_with_one_call_in_flight`。用假引擎，不加载原生库。
 */
class SortformerLocalClientTest {
    private class FakeEngine(
        private val onFeed: ((FloatArray, Boolean) -> Unit)? = null,
    ) : SortformerEngine {
        val calls = mutableListOf<Pair<Int, Boolean>>()
        val concurrent = AtomicInteger(0)
        var maxConcurrent = 0
        var closed = false
        private var consumed = 0L

        override fun feed(samples: FloatArray, flush: Boolean): SortformerFeedResult {
            val now = concurrent.incrementAndGet()
            synchronized(this) {
                maxConcurrent = maxOf(maxConcurrent, now)
                calls.add(samples.size to flush)
                consumed += samples.size
            }
            try {
                onFeed?.invoke(samples, flush)
                return SortformerFeedResult(emptyList(), melFrames = consumed / 160, samples = consumed)
            } finally {
                concurrent.decrementAndGet()
            }
        }

        override fun close() {
            closed = true
        }
    }

    private class Recorder : SortformerLocalObserver {
        val results = mutableListOf<SortformerLocalFeedResult>()
        val degraded = mutableListOf<Pair<SpeakerDiarizationDegradedReason, String>>()
        val drained = CountDownLatch(1)

        override fun onFeedResult(result: SortformerLocalFeedResult) {
            synchronized(results) { results.add(result) }
        }

        override fun onDrained() {
            drained.countDown()
        }

        override fun onDegraded(reason: SpeakerDiarizationDegradedReason, message: String) {
            synchronized(degraded) { degraded.add(reason to message) }
        }
    }

    private fun pcm(samples: Int): ByteArray = ByteArray(samples * 2)

    @Test
    fun audioIsBatchedAndFlushedOnceWithOneCallInFlight() {
        val engine = FakeEngine()
        val recorder = Recorder()
        val client = SortformerLocalClient(recorder, { engine }).also { it.start() }

        // 不足半秒不交给引擎：引擎只在块与预览边界动作，批量不改变结果。
        client.append(pcm(1_000))
        Thread.sleep(50)
        assertTrue("under the batch threshold must not reach the engine", engine.calls.isEmpty())

        client.append(pcm(SortformerLocalClient.FEED_MIN_SAMPLES))
        client.finish()
        assertTrue("drained within the timeout", recorder.drained.await(5, TimeUnit.SECONDS))

        assertEquals(1, engine.maxConcurrent)
        assertEquals(1, engine.calls.count { it.second })
        assertEquals(
            "every queued sample reaches the engine exactly once",
            1_000 + SortformerLocalClient.FEED_MIN_SAMPLES,
            engine.calls.sumOf { it.first },
        )
        assertTrue(recorder.results.last().flushed)
        assertTrue(recorder.degraded.isEmpty())
    }

    @Test
    fun aFlushHappensEvenWithoutEnoughAudioToBatch() {
        val engine = FakeEngine()
        val recorder = Recorder()
        val client = SortformerLocalClient(recorder, { engine }).also { it.start() }
        client.append(pcm(100))
        client.finish()
        assertTrue(recorder.drained.await(5, TimeUnit.SECONDS))
        assertEquals(listOf(100 to true), engine.calls)
    }

    @Test
    fun aBacklogBeyondTheCapDegradesInsteadOfGrowing() {
        // 引擎一直卡住，积压越过上限后应判定停滞而不是无声增长。
        val blocked = CountDownLatch(1)
        val engine = FakeEngine { _, _ -> blocked.await(5, TimeUnit.SECONDS) }
        val recorder = Recorder()
        val client = SortformerLocalClient(recorder, { engine }).also { it.start() }
        client.append(pcm(SortformerLocalClient.FEED_MIN_SAMPLES))
        Thread.sleep(50)
        client.append(pcm(SortformerLocalClient.MAX_PENDING_SAMPLES + 1))
        blocked.countDown()

        assertEquals(1, recorder.degraded.size)
        assertEquals(SpeakerDiarizationDegradedReason.INFERENCE_TIMEOUT, recorder.degraded[0].first)
        assertTrue(recorder.degraded[0].second.contains("behind the audio"))
        assertEquals(0, client.pendingWindowCount())
    }

    @Test
    fun aModelThatCannotOpenDegradesAndDrains() {
        val recorder = Recorder()
        SortformerLocalClient(recorder, { throw IllegalStateException("model missing") }).start()
        assertTrue(recorder.drained.await(5, TimeUnit.SECONDS))
        assertEquals(1, recorder.degraded.size)
        assertEquals(SpeakerDiarizationDegradedReason.INFERENCE_UNAVAILABLE, recorder.degraded[0].first)
    }

    @Test
    fun cancelClosesTheEngineAndReportsQuiescent() {
        val engine = FakeEngine()
        val recorder = Recorder()
        val client = SortformerLocalClient(recorder, { engine }).also { it.start() }
        Thread.sleep(50)
        val quiescent = CountDownLatch(1)
        client.cancel { quiescent.countDown() }
        assertTrue(quiescent.await(5, TimeUnit.SECONDS))
        assertTrue(engine.closed)
        assertEquals(0, client.pendingWindowCount())
    }

    @Test
    fun stopInferenceKeepsDeliveredResultsAndStartsNothingNew() {
        val engine = FakeEngine()
        val recorder = Recorder()
        val client = SortformerLocalClient(recorder, { engine }).also { it.start() }
        Thread.sleep(50)
        client.stopInference()
        client.append(pcm(SortformerLocalClient.FEED_MIN_SAMPLES))
        Thread.sleep(50)
        assertTrue("no call starts after stopInference", engine.calls.isEmpty())
        assertFalse(engine.closed)
    }

    @Test
    fun framesBecomeMillisecondsWithOpenEndedSpans() {
        val engine = FakeEngine()
        val recorder = Recorder()
        // 原生侧回报的帧区间 [0,120) 应变成毫秒 [0,1200)，端点不能差一帧。
        val withEvents = object : SortformerEngine {
            override fun feed(samples: FloatArray, flush: Boolean) = SortformerFeedResult(
                events = listOf(
                    SortformerEvent(
                        kind = "final",
                        beginFrame = 0,
                        frames = 992,
                        inferenceMs = 1.0,
                        runs = listOf(listOf(FrameSpan(0, 120)), emptyList(), emptyList(), emptyList()),
                    ),
                ),
                melFrames = 992,
                samples = 158_720,
            )

            override fun close() = engine.close()
        }
        val client = SortformerLocalClient(recorder, { withEvents }).also { it.start() }
        client.append(pcm(SortformerLocalClient.FEED_MIN_SAMPLES))
        client.finish()
        assertTrue(recorder.drained.await(5, TimeUnit.SECONDS))
        val span = recorder.results.first().events.first().runs[0].first()
        assertEquals(TimeSpan(0, 1_200), span)
        assertEquals(9_920L, recorder.results.first().events.first().endTime)
    }
}
