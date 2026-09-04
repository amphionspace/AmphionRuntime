package com.amphion.dingqiao.diarization

import android.content.Context
import com.amphion.asr.AsrResult
import com.amphion.asr.internal.ResultAudioTimeline
import com.amphion.dingqiao.*
import org.junit.Assert.*
import org.junit.Test
import org.mockito.Mockito.mockConstruction
import org.mockito.kotlin.mock
import java.nio.file.Files
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.Executors

class DiarizationWindowFinalizationTest {
    @Test fun windowPublicationCannotOvertakeAnEarlierUpdateDuringConcurrentDrain() {
        mockConstruction(SpeakerDiarizationLocalClient::class.java).use {
            val updating = CountDownLatch(1)
            val releaseUpdate = CountDownLatch(1)
            val results = java.util.concurrent.CopyOnWriteArrayList<SpeakerDiarizationResult>()
            val observer = object : SpeakerDiarizationSessionObserver {
                override fun onUpdate(update: SpeakerDiarizationUpdate) {
                    updating.countDown()
                    assertTrue(releaseUpdate.await(3, TimeUnit.SECONDS))
                }
                override fun onWindowResult(result: SpeakerDiarizationResult) { results += result }
                override fun onFinished(result: SpeakerDiarizationResult) = Unit
            }
            val directory = Files.createTempDirectory("diarization-order-test").toFile()
            val session = SpeakerDiarizationSession(mock<Context>(), directory, 4, observer)
            val final = AsrResult("词")
            ResultAudioTimeline.record(final, 120000 * 16L)
            session.observeAsrFinal(SpeechRecognitionResult(isFinal = true, result = "词",
                beginTime = 111000, endTime = 119000), final)
            session.asrFinalDelivered(final)
            val executor = Executors.newSingleThreadExecutor()
            try {
                val pending = executor.submit { session.onWindow(window(122500)) }
                assertTrue(updating.await(3, TimeUnit.SECONDS))
                session.asrFinalDelivered(final)
                assertTrue("window result overtook an earlier update", results.isEmpty())
                releaseUpdate.countDown()
                pending.get(3, TimeUnit.SECONDS)
                assertEquals(1, results.size)
            } finally {
                releaseUpdate.countDown()
                executor.shutdownNow()
                session.cancel()
                directory.deleteRecursively()
            }
        }
    }

    @Test fun publicationEvictsTextWithoutReusingIdsAndFreezesUnknown() {
        val transcript = DiarizationTranscriptState()
        val id = transcript.addUtterance("二十三", "23", listOf("二", "十", "三"), listOf(100, 200, 300), 0, 400)
        val frozen = transcript.commitThrough(1000)
        assertEquals("UNKNOWN", frozen.single().speakerId)
        assertEquals("23", frozen.single().text)
        assertTrue(transcript.applyEvidenceRemap(mapOf("old" to "S2")).isEmpty())
        assertTrue(transcript.finalUtterances().isEmpty())
        val next = transcript.addUtterance("新", "新", emptyList(), emptyList(), 1000, 2000)
        assertNotEquals(id, next)
        assertEquals(next, transcript.commitThrough(2000).single().sourceUtteranceId)
    }

    @Test fun committedIdentitiesCannotBeMergedBySimilarLaterEvidence() {
        val observations = listOf(
            SpeakerEmbeddingObservation(floatArrayOf(1f, 0f), 2000, "UNKNOWN", 1000, "a", "S1"),
            SpeakerEmbeddingObservation(floatArrayOf(0.99f, 0.01f), 2000, "UNKNOWN", 1000, "b", "S2"),
        )
        assertEquals(2, SpeakerDiarizationGlobalClusterer().cluster(observations).clusterCount)
    }

    @Test fun pcmBlocksRetainQueuedAudioAndReleaseOnlyConsumedBlocks() {
        val dir = Files.createTempDirectory("diarization-spool-test").toFile()
        try {
            val spool = DiarizationPcmSpool(dir)
            val source = ByteArray(700_000) { (it % 127).toByte() }
            source.asList().chunked(640).forEach { spool.append(it.toByteArray()) }
            assertArrayEquals(source.copyOfRange(300_000, 340_000), spool.read(300_000, 40_000))
            spool.discardBefore(319_999)
            assertEquals(3, dir.listFiles()!!.size)
            spool.discardBefore(320_000)
            assertEquals(2, dir.listFiles()!!.size)
            assertArrayEquals(source.copyOfRange(320_000, 640_000), spool.read(320_000, 320_000))
            spool.remove()
            assertEquals(0, dir.listFiles()!!.size)
        } finally { dir.deleteRecursively() }
    }

    @Test fun sessionResultsAreIdenticalWhenAsrOrDiarizationFinishesFirst() {
        val asrFirst = runSession(300_000, true)
        val inferenceFirst = runSession(300_000, false)
        assertEquals(asrFirst, inferenceFirst)
        assertEquals(listOf(0, 1, 2), asrFirst.map { it.windowIndex })
        assertEquals(listOf(false, false, true), asrFirst.map { it.isSessionFinal })
        assertEquals(30, asrFirst.sumOf { it.utterances.size })
    }

    @Test fun lateAsrCallbacksUseTheSameEvidenceAndKeepReturningSpeakerIdentity() {
        val speakers: (Int) -> FloatArray = { end ->
            if (end in 125001..242500) floatArrayOf(0f, 1f) else floatArrayOf(1f, 0f)
        }
        val immediate = runSession(360000, true, speakerForEnd = speakers)
        val delayed = runSession(360000, false, 15000, speakers)
        assertEquals(immediate, delayed)
        val utterances = immediate.flatMap { it.utterances }
        val a = utterances.first { it.beginTime == 1000 }.speakerIndex
        val b = utterances.first { it.beginTime == 161000 }.speakerIndex
        val returningA = utterances.first { it.beginTime == 281000 }.speakerIndex
        assertTrue(a >= 0)
        assertTrue(b >= 0)
        assertNotEquals(a, b)
        assertEquals(a, returningA)
    }

    @Test fun degradedWindowsFreezeUnknownAndAlwaysPublishAnEmptyTerminalBatch() {
        val results = mutableListOf<SpeakerDiarizationResult>()
        val observer = object : SpeakerDiarizationSessionObserver {
            override fun onUpdate(update: SpeakerDiarizationUpdate) = fail("degraded update")
            override fun onWindowResult(result: SpeakerDiarizationResult) { results += result }
            override fun onFinished(result: SpeakerDiarizationResult) { results += result }
        }
        val session = DegradedSpeakerDiarizationSession(4, observer,
            SpeakerDiarizationDegradedReason.MODEL_UNAVAILABLE, "unavailable")
        repeat(2) { index ->
            session.append(ByteArray(120000 * 32))
            val result = AsrResult("词")
            ResultAudioTimeline.record(result, (index + 1) * 120000 * 16L)
            session.observeAsrFinal(SpeechRecognitionResult(isFinal = true, result = "词",
                beginTime = index * 120000, endTime = (index + 1) * 120000), result)
            session.asrFinalDelivered(result)
        }
        session.finish()
        session.observeAsrFinal(SpeechRecognitionResult(isFinal = true, isLast = true), AsrResult("", isLast = true))
        assertEquals(listOf(0, 1, 2), results.map { it.windowIndex })
        assertEquals(listOf(false, false, true), results.map { it.isSessionFinal })
        assertTrue(results.last().utterances.isEmpty())
        assertEquals(listOf(-1, -1), results.flatMap { it.utterances }.map { it.speakerIndex })
        session.cancel()
        session.finish()
        assertEquals(3, results.size)
    }

    @Test fun fiveHoursOfAudioTimeDoesNotRetainPublishedTranscriptOrEmbeddings() {
        val results = runSession(5 * 60 * 60 * 1000, true)
        assertEquals(150, results.size)
        assertEquals(1, results.count { it.isSessionFinal })
        assertEquals(1800, results.sumOf { it.utterances.size })
    }

    private fun runSession(durationMs: Int, asrFirst: Boolean, asrDelayMs: Int = 0,
        speakerForEnd: (Int) -> FloatArray = { floatArrayOf(1f, 0f) }): List<SpeakerDiarizationResult> {
        mockConstruction(SpeakerDiarizationLocalClient::class.java).use {
            val results = mutableListOf<SpeakerDiarizationResult>()
            val frozen = mutableSetOf<String>()
            val observer = object : SpeakerDiarizationSessionObserver {
                override fun onUpdate(update: SpeakerDiarizationUpdate) {
                    assertFalse("update after publication: ${update.utteranceId}", update.utteranceId in frozen)
                }
                override fun onWindowResult(result: SpeakerDiarizationResult) { record(result) }
                override fun onFinished(result: SpeakerDiarizationResult) { record(result) }
                private fun record(result: SpeakerDiarizationResult) {
                    assertEquals(results.size, result.windowIndex)
                    result.utterances.forEach { assertTrue(frozen.add(it.utteranceId)) }
                    results += result.copy(inferenceMs = 0, rtf = 0f)
                }
            }
            val directory = Files.createTempDirectory("diarization-session-test").toFile()
            val session = SpeakerDiarizationSession(mock<Context>(), directory, 4, observer)
            val pendingAsr = java.util.ArrayDeque<Pair<Int, () -> Unit>>()
            val pcm = ByteArray(80_000)
            var firstSnapshot: SpeakerDiarizationResult? = null
            for (end in 2500..durationMs step 2500) {
                session.append(pcm)
                val final = if (end % 10_000 == 0) AsrResult("词", timestamps = listOf((end - 9000) / 1000f, (end - 1000) / 1000f)) else null
                if (final != null) ResultAudioTimeline.record(final, end * 16L)
                fun deliverAsr() {
                    if (final == null) return
                    session.observeAsrFinal(SpeechRecognitionResult(isFinal = true, result = "词", beginTime = end - 9000, endTime = end - 1000), final)
                    session.asrFinalDelivered(final)
                }
                if (asrDelayMs > 0 && final != null) pendingAsr.addLast(end + asrDelayMs to { deliverAsr() })
                if (asrDelayMs == 0 && asrFirst) deliverAsr()
                session.onWindow(window(end, speakerForEnd(end)))
                if (asrDelayMs == 0 && !asrFirst) deliverAsr()
                while (pendingAsr.isNotEmpty() && pendingAsr.first().first <= end) pendingAsr.removeFirst().second()
                if (results.isNotEmpty()) {
                    if (firstSnapshot == null) firstSnapshot = results.first().copy(utterances = results.first().utterances.toList(), speakerTurns = results.first().speakerTurns.toList())
                    assertEquals(firstSnapshot, results.first())
                }
                val observations = session.javaClass.getDeclaredField("recentObservations").apply { isAccessible = true }.get(session) as List<*>
                assertTrue("unbounded embedding history: ${observations.size}", observations.size <= 50 + asrDelayMs / 2500)
            }
            while (pendingAsr.isNotEmpty()) pendingAsr.removeFirst().second()
            session.finish()
            session.observeAsrFinal(SpeechRecognitionResult(isFinal = true, isLast = true), AsrResult("", isLast = true))
            session.onDrained()
            session.cancel()
            session.onWindow(window(durationMs + 2500))
            directory.deleteRecursively()
            return results
        }
    }

    private fun window(end: Int, embedding: FloatArray = floatArrayOf(1f, 0f)): DiarizationLocalWindowResult {
        val sampleEnd = end * 16L
        val realCount = minOf(sampleEnd, 160_000).toInt()
        val padding = 160_000 - realCount
        return DiarizationLocalWindowResult("w$end", maxOf(0, sampleEnd - 160_000), padding,
            sampleEnd, maxOf(0, sampleEnd - 40_000 - 24_000), maxOf(0, sampleEnd - 24_000), false,
            DiarizationWindowInferenceResult(
                listOf(SpeakerSegmentationSegment(padding, 160_000, 0, 1)),
                listOf(DiarizationEmbedding(0, 40_000, embedding)), 1))
    }
}
