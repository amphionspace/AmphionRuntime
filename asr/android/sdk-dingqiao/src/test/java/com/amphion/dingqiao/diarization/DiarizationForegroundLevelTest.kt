package com.amphion.dingqiao.diarization

import android.content.Context
import com.amphion.asr.AsrResult
import com.amphion.dingqiao.SpeakerDiarizationResult
import com.amphion.dingqiao.SpeakerDiarizationUpdate
import com.amphion.dingqiao.SpeechRecognitionResult
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.mockito.Mockito.mockConstruction
import org.mockito.kotlin.mock
import java.nio.file.Files

class DiarizationForegroundLevelTest {
    @Test fun laterLoudVoicePreservesAnIndependentlyAdmittedNewPerson() {
        mockConstruction(SpeakerDiarizationLocalClient::class.java).use {
            val directory = Files.createTempDirectory("diarization-admitted-person").toFile()
            val results = mutableListOf<SpeakerDiarizationResult>()
            val session = SpeakerDiarizationSession(mock<Context>(), directory, 4,
                object : SpeakerDiarizationSessionObserver {
                    override fun onUpdate(update: SpeakerDiarizationUpdate) = Unit
                    override fun onFinished(result: SpeakerDiarizationResult) { results += result }
                })
            try {
                session.append(ByteArray(30000 * 32))
                val cases = listOf(0 to .1, 1 to .06, 0 to .06, 2 to .15, 3 to .02)
                cases.forEachIndexed { i, (person, rms) ->
                    val begin = i * 96000L
                    val vector = FloatArray(4) { if (it == person) 1f else 0f }
                    session.onWindow(DiarizationLocalWindowResult("w$i", begin, 0, begin + 96000,
                        begin, begin + 96000, false, DiarizationWindowInferenceResult(
                            listOf(SpeakerSegmentationSegment(0, 96000, 0, 1, vector)),
                            listOf(DiarizationEmbedding(0, 96000, vector, vector, rms)), 0)))
                }
                session.finish()
                session.observeAsrFinal(SpeechRecognitionResult(isFinal = true, isLast = true), AsrResult("", isLast = true))
                session.onDrained()
                val result = results.single()
                val ids = result.speakerTurns.map { it.speakerIndex }
                assertTrue("Later loud speech must not erase an admitted new person", ids[1] >= 0)
                assertEquals(3, setOf(ids[0], ids[1], ids[3]).size)
                assertEquals(3, result.speakerCount)
                assertEquals("Existing quiet identity recovery must stay unchanged", -1, ids[2])
                assertEquals("Never-admitted background cannot enroll", -1, ids[4])
            } finally { session.cancel(); directory.deleteRecursively() }
        }
    }

    @Test fun laterLouderSpeechRevisesOnlyUncommittedQuietEvidence() {
        mockConstruction(SpeakerDiarizationLocalClient::class.java).use {
            val directory = Files.createTempDirectory("diarization-later-foreground-test").toFile()
            val results = mutableListOf<SpeakerDiarizationResult>()
            val observer = object : SpeakerDiarizationSessionObserver {
                override fun onUpdate(update: SpeakerDiarizationUpdate) = Unit
                override fun onFinished(result: SpeakerDiarizationResult) { results += result }
            }
            val session = SpeakerDiarizationSession(mock<Context>(), directory, 4, observer)
            try {
                session.append(ByteArray(10000 * 32))
                repeat(2) { i ->
                    val begin = i * 80000L
                    val vector = if (i == 0) floatArrayOf(1f, 0f) else floatArrayOf(0f, 1f)
                    session.onWindow(DiarizationLocalWindowResult("w$i", begin, 0, begin + 80000,
                        begin, begin + 80000, false, DiarizationWindowInferenceResult(
                            listOf(SpeakerSegmentationSegment(0, 80000, 0, 1)),
                            listOf(DiarizationEmbedding(0, 80000, vector, vector,
                                if (i == 0) .01 else .1)), 0)))
                }
                session.finish()
                session.observeAsrFinal(SpeechRecognitionResult(isFinal = true, isLast = true),
                    AsrResult("", isLast = true))
                session.onDrained()
                assertEquals(listOf(-1, 0), results.single().speakerTurns.map { it.speakerIndex })
                assertEquals(1, results.single().speakerCount)
            } finally {
                session.cancel()
                directory.deleteRecursively()
            }
        }
    }

    @Test fun quieterBackgroundCannotDisplaceFourPrincipalVoices() {
        mockConstruction(SpeakerDiarizationLocalClient::class.java).use {
            fun replay(gain: Double): Pair<List<String>, List<Int>> {
                val directory = Files.createTempDirectory("diarization-foreground-test").toFile()
                val results = mutableListOf<SpeakerDiarizationResult>()
                val observer = object : SpeakerDiarizationSessionObserver {
                    override fun onUpdate(update: SpeakerDiarizationUpdate) = Unit
                    override fun onFinished(result: SpeakerDiarizationResult) { results += result }
                }
                val session = SpeakerDiarizationSession(mock<Context>(), directory, 4, observer)
                try {
                    session.append(ByteArray(40000 * 32))
                    listOf(0, 4, 1, 5, 2, 3, 0, 1, 2, 3).forEachIndexed { i, id ->
                        val begin = i * 4000L * 16
                        val end = begin + 64000
                        val vector = FloatArray(6) { if (it == id) 1f else 0f }
                        session.onWindow(DiarizationLocalWindowResult("w$i", begin, 0, end, begin, end,
                            false, DiarizationWindowInferenceResult(
                                listOf(SpeakerSegmentationSegment(0, 64000, 0, 1)),
                                listOf(DiarizationEmbedding(0, 64000, vector, vector,
                                    (if (id >= 4) .01 else .1) * gain)), 0)))
                    }
                    val transcript = session.javaClass.getDeclaredField("transcript")
                        .apply { isAccessible = true }.get(session) as DiarizationTranscriptState
                    val online = transcript.allTurns().map { it.speakerId }
                    session.finish()
                    session.observeAsrFinal(SpeechRecognitionResult(isFinal = true, isLast = true),
                        AsrResult("", isLast = true))
                    session.onDrained()
                    assertEquals(4, results.single().speakerCount)
                    return online to results.single().speakerTurns.map { it.speakerIndex }
                } finally {
                    session.cancel()
                    directory.deleteRecursively()
                }
            }
            val normal = replay(1.0)
            assertEquals(listOf("S1", "UNKNOWN", "S2", "UNKNOWN", "S3", "S4", "S1", "S2", "S3", "S4"), normal.first)
            assertEquals(listOf(0, -1, 1, -1, 2, 3, 0, 1, 2, 3), normal.second)
            assertEquals(normal, replay(.1))
        }
    }
}
