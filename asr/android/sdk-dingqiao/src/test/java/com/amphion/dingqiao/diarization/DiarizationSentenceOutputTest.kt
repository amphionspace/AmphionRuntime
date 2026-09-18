package com.amphion.dingqiao.diarization

import org.junit.Assert.*
import org.junit.Test

class DiarizationSentenceOutputTest {
    private fun turn(begin: Int, end: Int, id: String, secondary: List<String> = emptyList()) =
        SpeakerTimelineTurn(begin, end, id, secondary, .8f, overlap = secondary.isNotEmpty())

    private fun sample(turns: List<SpeakerTimelineTurn>, end: Int = 1000, times: List<Int> = listOf(100, 700)) =
        DiarizationTranscriptState().apply {
            addUtterance("张三", "张三。", listOf("张", "三"), times, 0, end)
            applySpeakerTurns(turns)
        }

    @Test fun mixedAndOverlappingSentenceHasNoSingleOwner() {
        for (turns in listOf(
            listOf(turn(0, 600, "S1"), turn(600, 1000, "S2")),
            listOf(turn(0, 250, "S1"), turn(250, 270, "S2"), turn(270, 1000, "S1")),
            listOf(turn(0, 1000, "S1", listOf("S2"))),
            listOf(turn(0, 1000, "S1", listOf("UNKNOWN"))),
            listOf(turn(0, 1000, "UNKNOWN")),
        )) {
            val state = sample(turns)
            val before = state.allTurns()
            val result = state.sentenceUtterances().single()
            assertEquals("张三。", result.text)
            assertEquals("张三", result.rawText)
            assertEquals("UNKNOWN", result.speakerId)
            assertEquals(0f, result.confidence)
            assertFalse(result.speakerInferred)
            assertEquals("UNKNOWN", state.currentAssignment("u1")!!.speakerId)
            assertEquals(before, state.allTurns())
            assertEquals(listOf(result), state.commitThrough(1000))
            assertTrue(state.sentenceUtterances().isEmpty())
        }
    }

    @Test fun boundedBackfillCannotChainUnknownCellsOrPropagateAcrossSentences() {
        val state = sample(listOf(turn(0, 500, "S1"), turn(500, 1000, "UNKNOWN")))
        val first = state.sentenceUtterances().single()
        assertEquals("S1", first.speakerId)
        assertTrue(first.speakerInferred)
        assertEquals(0f, first.confidence)
        state.addUtterance("嗯", "嗯。", listOf("嗯"), listOf(1100), 1000, 1300)
        state.applySpeakerTurns(listOf(turn(1000, 1300, "UNKNOWN")))
        assertEquals("UNKNOWN", state.sentenceUtterances().last().speakerId)
        val long = sample(listOf(turn(0, 200, "S1"), turn(200, 1700, "UNKNOWN"),
            turn(1700, 3200, "UNKNOWN"), turn(3200, 4000, "S1")), 4000, listOf(100, 3500))
        assertEquals("UNKNOWN", long.sentenceUtterances().single().speakerId)
    }
}
