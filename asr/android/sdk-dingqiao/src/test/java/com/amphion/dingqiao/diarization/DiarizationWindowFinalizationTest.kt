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
    @Test fun hiddenSecondaryKeepsItsEvidenceBindingAcrossPartialRemaps() {
        val transcript = DiarizationTranscriptState()
        transcript.applySpeakerTurns(listOf(SpeakerTimelineTurn(0, 2000, "S1", listOf("S2", "S3"),
            evidenceKey = "a", secondaryEvidenceKeys = listOf("b", "c"))))
        transcript.applyEvidenceRemap(mapOf("a" to "S1", "b" to "S1", "c" to "S3"))
        assertEquals(listOf("S3"), transcript.allTurns().single().secondarySpeakerIds)
        transcript.applyEvidenceRemap(mapOf("b" to "S2"))
        assertEquals(listOf("S2", "S3"), transcript.allTurns().single().secondarySpeakerIds)
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
            session.asrAudioProcessed((index + 1) * 120000 * 16L)
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

}
