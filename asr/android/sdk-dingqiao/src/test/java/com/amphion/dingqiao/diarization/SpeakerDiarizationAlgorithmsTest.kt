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
    fun boundedUnknownBackfillPreservesAcousticEvidenceAndRealTurns() {
        fun turn(start: Int, end: Int, id: String) = SpeakerTimelineTurn(start, end, id, emptyList(), 0.9f)
        fun state(text: String, times: List<Int>, end: Int, turns: List<SpeakerTimelineTurn>): DiarizationTranscriptState {
            val state = DiarizationTranscriptState()
            state.addUtterance(text, "$text。", text.map { it.toString() }, times, 0, end)
            state.applySpeakerTurns(turns)
            return state
        }
        val sample = state("张三", listOf(100, 500), 900,
            listOf(turn(0, 500, "S1"), turn(500, 900, "UNKNOWN")))
        val before = sample.allTurns()
        val fixed = sample.finalUtterances().single()
        assertEquals("张三。", fixed.text)
        assertEquals("S1", fixed.speakerId)
        assertTrue(fixed.speakerInferred)
        assertEquals(0f, fixed.confidence)
        assertEquals(before, sample.allTurns())
        assertEquals(listOf(fixed), sample.commitThrough(900))
        assertTrue(sample.finalUtterances().isEmpty())
        for (turns in listOf(
            listOf(turn(0, 500, "UNKNOWN"), turn(500, 900, "S1")),
            listOf(turn(0, 200, "S1"), turn(200, 500, "UNKNOWN"), turn(500, 900, "S1")),
        )) {
            val result = state("你好啊", listOf(100, 300, 600), 900, turns).finalUtterances().single()
            assertEquals("S1", result.speakerId)
            assertTrue(result.speakerInferred)
        }
        for (duration in listOf(2500, 2501)) {
            val result = state("甲乙", listOf(100, 500), 500 + duration,
                listOf(turn(0, 500, "S1"), turn(500, 500 + duration, "UNKNOWN"))).finalUtterances()
            assertEquals(if (duration == 2500) listOf("S1") else listOf("S1", "UNKNOWN"), result.map { it.speakerId })
        }
        assertEquals(listOf("S1", "UNKNOWN", "S2"), state("甲嗯乙", listOf(100, 500, 900), 1200,
            listOf(turn(0, 500, "S1"), turn(500, 900, "UNKNOWN"), turn(900, 1200, "S2")))
            .finalUtterances().map { it.speakerId })
        for (uncertain in listOf(turn(500, 900, "UNKNOWN").copy(overlap = true),
            SpeakerTimelineTurn(500, 900, "UNKNOWN", listOf("S2"), 0.9f))) {
            assertEquals(listOf("S1", "UNKNOWN"), state("甲乙", listOf(100, 500), 900,
                listOf(turn(0, 500, "S1"), uncertain)).finalUtterances().map { it.speakerId })
        }
        assertEquals(listOf("S1", "UNKNOWN"), state("甲乙", listOf(100, 500), 900,
            listOf(turn(0, 500, "S1"), turn(500, 600, "UNKNOWN"), turn(600, 650, "S2"),
                turn(650, 900, "UNKNOWN"))).finalUtterances().map { it.speakerId })
        val alone = state("甲", listOf(100), 900, listOf(turn(0, 900, "UNKNOWN")))
        alone.addUtterance("乙", "乙", listOf("乙"), listOf(1000), 900, 1200)
        alone.applySpeakerTurns(listOf(turn(900, 1200, "S1")))
        assertEquals(listOf("UNKNOWN", "S1"), alone.finalUtterances().map { it.speakerId })
    }

    @Test
    fun secondaryChangesDoNotFragmentPrimarySpeechOrEraseOverlap() {
        val state = DiarizationTranscriptState()
        state.addUtterance("你叫什么名字", "你叫什么名字。", listOf("你", "叫", "什", "么", "名", "字"),
            listOf(100, 300, 500, 700, 900, 1100), 0, 1200)
        state.applySpeakerTurns(listOf(
            SpeakerTimelineTurn(0, 250, "S1", emptyList()),
            SpeakerTimelineTurn(250, 450, "S1", listOf("UNKNOWN_SECONDARY"), overlap = true),
            SpeakerTimelineTurn(450, 650, "S1", listOf("S2"), overlap = true),
            SpeakerTimelineTurn(650, 1200, "S1", emptyList()),
        ))
        val before = state.allTurns()
        val result = state.finalUtterances()
        assertEquals(listOf("你叫什么名字。"), result.map { it.text })
        assertEquals("S1", result.single().speakerId)
        assertEquals(listOf("UNKNOWN_SECONDARY", "S2"), result.single().secondarySpeakerIds)
        assertTrue(result.single().overlap)
        assertEquals(before, state.allTurns())

        val short = DiarizationTranscriptState()
        short.addUtterance("嗯好", "嗯，好。", listOf("嗯", "好"), listOf(100, 700), 0, 1000)
        short.applySpeakerTurns(listOf(
            SpeakerTimelineTurn(0, 250, "S1", emptyList()),
            SpeakerTimelineTurn(250, 300, "S1", listOf("S2"), overlap = true),
            SpeakerTimelineTurn(300, 600, "S1", emptyList()),
            SpeakerTimelineTurn(600, 1000, "S2", emptyList()),
        ))
        val split = short.commitThrough(1000)
        assertEquals(listOf("嗯，" to "S1", "好。" to "S2"), split.map { it.text to it.speakerId })
        assertEquals(listOf("S2"), split.first().secondarySpeakerIds)
        assertTrue(split.first().overlap)
        assertTrue(short.finalUtterances().isEmpty())
    }

    @Test
    fun unanimousSpeakerAndBoundedBackfillKeepConflictingOrOverlappingTurns() {
        fun split(turns: List<SpeakerTimelineTurn>): List<String> {
            val state = DiarizationTranscriptState()
            state.addUtterance("甲乙丙", "甲乙丙。", listOf("甲", "乙", "丙"),
                listOf(100, 600, 1100), 0, 1200)
            state.applySpeakerTurns(turns)
            return state.finalUtterances().map { it.speakerId }
        }
        val first = SpeakerTimelineTurn(0, 500, "S1", emptyList())
        val second = SpeakerTimelineTurn(700, 1000, "S1", emptyList())
        assertEquals(listOf("S1"), split(listOf(first, second)))
        assertEquals(listOf("S1"), split(listOf(first,
            SpeakerTimelineTurn(500, 1200, "UNKNOWN", emptyList()))))
        assertEquals(listOf("S1", "UNKNOWN"), split(listOf(first, second.copy(speakerId = "S2"))))
        assertEquals(listOf("S1", "UNKNOWN"), split(listOf(first.copy(overlap = true,
            secondarySpeakerIds = listOf("S2")))))
        assertEquals(listOf("UNKNOWN"), split(emptyList()))
    }

    @Test
    fun bbpeAlignmentKeepsTheFirstByteTimestampAndWholeCharacters() {
        val state = DiarizationTranscriptState()
        state.addUtterance("你好啊", "你好，啊。", listOf("▁Ƌ", "ţŅƌŋţ", "▁ƌĸī"),
            listOf(100, 300, 1200), 0, 2000)
        state.applySpeakerTurns(listOf(
            SpeakerTimelineTurn(0, 200, "S1", emptyList()),
            SpeakerTimelineTurn(200, 1000, "S2", emptyList()),
            SpeakerTimelineTurn(1000, 2000, "S3", emptyList()),
        ))
        val split = state.finalUtterances()
        assertEquals(listOf("你", "好", "啊"), split.map { it.rawText })
        assertEquals(listOf("你", "好，", "啊。"), split.map { it.text })
        assertEquals(listOf("S1", "S2", "S3"), split.map { it.speakerId })
        val english = DiarizationTranscriptState()
        english.addUtterance("HELLO WORLD", "HELLO, WORLD.", listOf("▁HELLO", "▁WORLD"),
            listOf(100, 1100), 0, 2000)
        english.applySpeakerTurns(listOf(SpeakerTimelineTurn(0, 1000, "S1", emptyList()),
            SpeakerTimelineTurn(1000, 2000, "S2", emptyList())))
        assertEquals("HELLO, WORLD.", english.finalUtterances().joinToString("") { it.text })
        assertEquals(listOf("S1", "S2"), english.finalUtterances().map { it.speakerId })
    }

    @Test
    fun punctuationPreservesTimedSpeakersAndUnknownWithoutRewritingText() {
        for (text in listOf("甲乙丙丁", "甲乙，丙丁。", " 甲乙！丙丁？")) {
            val state = DiarizationTranscriptState()
            state.addUtterance("甲乙丙丁", text, listOf("甲", "乙", "丙", "丁"),
                listOf(100, 500, 1000, 1500), 0, 2000)
            state.applySpeakerTurns(listOf(
                SpeakerTimelineTurn(0, 900, "S1", emptyList()),
                SpeakerTimelineTurn(900, 2000, "UNKNOWN", listOf("S2"), overlap = true),
            ))
            val split = state.commitThrough(2000)
            assertEquals(listOf("S1", "UNKNOWN"), split.map { it.speakerId })
            assertEquals(text, split.joinToString("") { it.text })
            assertEquals("甲乙丙丁", split.joinToString("") { it.rawText })
            assertEquals(listOf(0 to 1000, 1000 to 2000), split.map { it.beginTime to it.endTime })
            assertEquals(listOf("u1", "u1"), split.map { it.sourceUtteranceId })
            assertTrue(split.last().overlap)
            assertTrue(state.finalUtterances().isEmpty())
            if (text == "甲乙，丙丁。") assertEquals(listOf("甲乙，", "丙丁。"), split.map { it.text })
        }
        for (text in listOf("23。", "甲戊，丙丁。")) {
            val state = DiarizationTranscriptState()
            state.addUtterance("甲乙丙丁", text, listOf("甲", "乙", "丙", "丁"),
                listOf(100, 500, 1000, 1500), 0, 2000)
            assertEquals(listOf(text), state.finalUtterances().map { it.text })
        }
    }

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
    fun finishBarrierWaitsForRealAsrBeforeStartingDiarizationTimeout() {
        val scheduler = Executors.newSingleThreadScheduledExecutor()
        try {
            for (speakerFirst in listOf(false, true)) {
                val outputs = mutableListOf<DiarizationFinishOutput<String, String>>()
                val barrier = SpeakerDiarizationFinishBarrier<String, String>(20, scheduler, {
                    outputs += it
                })
                barrier.begin()
                if (speakerFirst) barrier.resolveSpeaker(DiarizationFinishInput(false, "speakers"))
                scheduler.schedule({}, 40, TimeUnit.MILLISECONDS).get(1, TimeUnit.SECONDS)
                assertTrue("ASR must drain accepted audio before last/complete", outputs.isEmpty())
                barrier.resolveAsr("actual-tail-after-draining")
                if (!speakerFirst) {
                    assertTrue(outputs.isEmpty())
                    scheduler.schedule({}, 40, TimeUnit.MILLISECONDS).get(1, TimeUnit.SECONDS)
                }
                assertEquals(1, outputs.size)
                assertEquals("actual-tail-after-draining", outputs.single().asr)
                assertEquals(if (speakerFirst) "speakers" else null, outputs.single().speaker)
                assertEquals(!speakerFirst, outputs.single().degraded)
                barrier.resolveAsr("duplicate")
                barrier.resolveSpeaker(DiarizationFinishInput(false, "late-speakers"))
                assertEquals(1, outputs.size)
            }
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
            })
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
