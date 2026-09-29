package com.amphion.dingqiao.diarization

import org.junit.Assert.*
import org.junit.Test

class DiarizationSentenceOutputTest {
    @Test fun ctSpacingChangesPreserveSpeakerOwnershipWithoutGuessingEnglishWords() {
        for ((raw, text, speaker) in listOf(
            Triple("你好 世界", "你好世界。", "S1"),
            Triple("hello 世界", "hello世界。", "S1"),
            Triple("你好 world", "你好world。", "S1"),
            Triple("hello world", "hello，world。", "S1"),
            Triple(" hello", "hello。", "S1"),
            Triple("hello world", "helloworld。", "UNKNOWN"),
            Triple("你好 世界", "你好地球。", "UNKNOWN"),
        )) {
            val state = DiarizationTranscriptState()
            state.addUtterance(raw, text, raw.map { it.toString() },
                raw.indices.map { it * 100 }, 0, 2000)
            state.applySpeakerTurns(listOf(turn(0, 2000, "S1")))
            val before = state.allTurns()
            val result = state.sentenceUtterances().single()
            assertEquals(raw, speaker, result.speakerId)
            assertEquals(text, result.text)
            assertEquals(raw, result.rawText)
            assertFalse(result.speakerInferred)
            assertEquals(before, state.allTurns())
        }
    }

    @Test fun punctuationCannotChangeOriginalUtteranceTailInference() {
        val raw = "可以听见我说话吗你好"
        for (text in listOf("可以听见我说话吗？你好。", "可以听见我说话吗你好。")) {
            val state = DiarizationTranscriptState()
            state.addUtterance(raw, text, raw.map { it.toString() },
                listOf(19700, 19740, 19820, 19900, 20020, 20140, 20300, 20460, 20660, 20860), 19700, 20860)
            state.applySpeakerTurns(listOf(turn(19600, 20652, "S1")))
            val before = state.allTurns()
            val result = state.sentenceUtterances().single()
            assertEquals("S1", result.speakerId)
            assertTrue(result.speakerInferred)
            assertEquals(0f, result.confidence)
            assertEquals(text, result.text)
            assertEquals(before, state.allTurns())
        }
    }

    @Test fun lexicalRewriteWithoutProvenanceDoesNotInventAnOwner() {
        for ((raw, text) in listOf("一百元" to "100元。", "百分之三" to "3%。", "三" to "THREE。")) {
            val state = DiarizationTranscriptState()
            state.addUtterance(raw, text, raw.map { it.toString() }, raw.indices.map { it * 100 }, 0, 1000)
            state.applySpeakerTurns(listOf(turn(0, 1000, "S1")))
            val result = state.sentenceUtterances().single()
            assertEquals(raw, result.rawText)
            assertEquals(text, result.text)
            assertEquals("UNKNOWN", result.speakerId)
            assertFalse(result.speakerInferred)
            assertEquals(0f, result.confidence)
        }
    }

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
