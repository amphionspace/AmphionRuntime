package com.amphion.dingqiao.diarization

import com.amphion.asr.AsrResult
import com.amphion.dingqiao.SpeakerDiarizationDegradedReason
import com.amphion.dingqiao.SpeakerDiarizationResult
import com.amphion.dingqiao.SpeakerDiarizationUpdate
import com.amphion.dingqiao.SpeechRecognitionResult
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class SpeakerDiarizationAlgorithmsTest {
    @Test
    fun schedulerMatchesHarmonyWindowHopAndFinalFlush() {
        val scheduler = DiarizationWindowScheduler(16_000)
        val first = scheduler.acceptSamples(40_000).single()
        assertEquals(40_000, first.realEndSample)
        assertEquals(0, first.commitStartSample)
        assertEquals(16_000, first.stableEndSample)
        assertFalse(first.finalWindow)

        val final = scheduler.finish()
        assertEquals(40_000, final.realEndSample)
        assertEquals(16_000, final.commitStartSample)
        assertEquals(40_000, final.stableEndSample)
        assertTrue(final.finalWindow)
    }

    @Test
    fun transcriptPublishesRevisionAndPreservesOverlap() {
        val transcript = DiarizationTranscriptState()
        val id = transcript.addUtterance(
            rawText = "你好",
            text = "你好",
            tokens = listOf("你", "好"),
            tokenTimesMs = listOf(100, 600),
            beginTime = 0,
            endTime = 1_000,
        )
        val updates = transcript.applySpeakerTurns(
            listOf(
                SpeakerTimelineTurn(0, 500, "S1", emptyList()),
                SpeakerTimelineTurn(500, 1_000, "S2", listOf("S1"), overlap = true),
            ),
        )
        assertEquals(id, updates.single().utteranceId)
        assertEquals(1, updates.single().revision)
        val final = transcript.finalUtterances()
        assertEquals(listOf("你", "好"), final.map { it.text })
        assertEquals(listOf("S1", "S2"), final.map { it.speakerId })
        assertTrue(final.last().overlap)
    }

    @Test
    fun globalClusterKeepsDistinctSpeakersAndStableDisplayIds() {
        val observations = listOf(
            observation(floatArrayOf(1f, 0f), "S2", "a"),
            observation(floatArrayOf(0.99f, 0.01f), "S2", "b"),
            observation(floatArrayOf(0f, 1f), "S1", "c"),
        )
        val result = SpeakerDiarizationGlobalClusterer(4, 0.72f).cluster(observations)
        assertEquals(2, result.clusterCount)
        assertEquals(result.observationSpeakerIds[0], result.observationSpeakerIds[1])
        assertTrue(result.observationSpeakerIds[0] != result.observationSpeakerIds[2])
        assertEquals("S2", result.observationSpeakerIds[0])
        assertEquals("S1", result.observationSpeakerIds[2])
    }

    @Test
    fun finishBarrierWaitsForBothAndCompletesOnce() {
        val scheduler = Executors.newSingleThreadScheduledExecutor()
        try {
            val latch = CountDownLatch(1)
            val outputs = mutableListOf<DiarizationFinishOutput<String, String>>()
            val barrier = SpeakerDiarizationFinishBarrier<String, String>(1_000, scheduler, {
                outputs += it
                latch.countDown()
            })
            barrier.begin()
            barrier.resolveAsr("last")
            assertFalse(latch.await(20, TimeUnit.MILLISECONDS))
            barrier.resolveSpeaker(DiarizationFinishInput(false, "speakers"))
            barrier.resolveSpeaker(DiarizationFinishInput(true, "ignored"))
            assertTrue(latch.await(1, TimeUnit.SECONDS))
            assertEquals(1, outputs.size)
            assertEquals("last", outputs.single().asr)
            assertEquals("speakers", outputs.single().speaker)
            assertFalse(outputs.single().degraded)
        } finally {
            scheduler.shutdownNow()
        }
    }

    @Test
    fun finishBarrierTimeoutUsesOneDegradedFallback() {
        val scheduler = Executors.newSingleThreadScheduledExecutor()
        try {
            val latch = CountDownLatch(1)
            val outputs = mutableListOf<DiarizationFinishOutput<String, String>>()
            val barrier = SpeakerDiarizationFinishBarrier<String, String>(20, scheduler, {
                outputs += it
                latch.countDown()
            }, timeoutAsrFallback = { "fallback-last" })
            barrier.begin()
            assertTrue(latch.await(1, TimeUnit.SECONDS))
            barrier.resolveAsr("late-last")
            barrier.resolveSpeaker(DiarizationFinishInput(false, "late-speakers"))
            assertEquals(1, outputs.size)
            assertEquals("fallback-last", outputs.single().asr)
            assertEquals(null, outputs.single().speaker)
            assertTrue(outputs.single().degraded)
        } finally {
            scheduler.shutdownNow()
        }
    }

    @Test
    fun cancelledFinishBarrierNeverPublishesTerminalOutput() {
        val scheduler = Executors.newSingleThreadScheduledExecutor()
        try {
            val latch = CountDownLatch(1)
            val barrier = SpeakerDiarizationFinishBarrier<String, String>(20, scheduler, {
                latch.countDown()
            }, timeoutAsrFallback = { "fallback-last" })
            barrier.begin()
            barrier.cancel()
            barrier.resolveAsr("last")
            barrier.resolveSpeaker(DiarizationFinishInput(false, "speakers"))
            assertFalse(latch.await(100, TimeUnit.MILLISECONDS))
        } finally {
            scheduler.shutdownNow()
        }
    }

    @Test
    fun globalSpeakerRemapPublishesRevisionAndStableFinalAssignment() {
        val transcript = DiarizationTranscriptState()
        val id = transcript.addUtterance("测试", "测试", emptyList(), emptyList(), 0, 1_000)
        transcript.applySpeakerTurns(listOf(SpeakerTimelineTurn(0, 1_000, "S1", listOf("S2"))))
        val updates = transcript.applySpeakerRemap(mapOf("S1" to "S3", "S2" to "S4"))
        assertEquals(id, updates.single().utteranceId)
        assertEquals(2, updates.single().revision)
        assertEquals("S3", updates.single().speakerId)
        assertEquals(listOf("S4"), updates.single().secondarySpeakerIds)
        assertEquals("S3", transcript.finalUtterances().single().speakerId)
    }

    @Test
    fun initializationStorageFailureKeepsAsrTailAndPublishesExplicitDegradation() {
        val results = mutableListOf<SpeakerDiarizationResult>()
        val session = DegradedSpeakerDiarizationSession(
            4,
            object : SpeakerDiarizationSessionObserver {
                override fun onUpdate(update: SpeakerDiarizationUpdate) = Unit
                override fun onFinished(result: SpeakerDiarizationResult) { results += result }
            },
            SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE,
            "sandbox unavailable",
        )
        session.append(ByteArray(32_000))
        session.finish()
        assertTrue(results.isEmpty())
        val payload = session.observeAsrFinal(
            SpeechRecognitionResult(true, true, "测试"),
            AsrResult("测试", rawText = "测试", isLast = true),
        )
        assertEquals("u1", payload.utteranceId)
        assertEquals(1, results.size)
        assertTrue(results.single().degraded)
        assertEquals(SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE, results.single().degradedReason)
        assertEquals("测试", results.single().utterances.single().text)
        assertEquals(-1, results.single().utterances.single().speakerIndex)
    }

    private fun observation(embedding: FloatArray, speaker: String, key: String) =
        SpeakerEmbeddingObservation(embedding, 2_000, speaker, 1_000, key)
}
