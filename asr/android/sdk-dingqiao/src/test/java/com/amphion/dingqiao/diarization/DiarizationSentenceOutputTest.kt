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

    @Test fun ctSpacingChangesKeepTokenOwnersAcrossRealSpeakerChanges() {
        // CT drops the separators before "report" and "result" and replaces the
        // others with sentence punctuation; each sits on a real speaker change.
        val raw = "先讨论 report 张三说明 result 嗯"
        val text = "先讨论report。张三说明result。嗯。"
        val state = DiarizationTranscriptState()
        state.addUtterance(raw, text, raw.map { it.toString() }, raw.indices.map { it * 100 }, 0, 2400)
        state.applySpeakerTurns(listOf(turn(0, 1050, "S1"), turn(1050, 2250, "S2"), turn(2250, 2400, "S1")))
        val before = state.allTurns()
        val result = state.finalUtterances()
        assertEquals(listOf("先讨论report。" to "S1", "张三说明result。" to "S2", "嗯。" to "S1"),
            result.map { it.text to it.speakerId })
        assertEquals(raw, result.joinToString("") { it.rawText })
        assertEquals(text, result.joinToString("") { it.text })
        assertTrue(result.none { it.speakerInferred })
        assertEquals(before, state.allTurns())
    }

    @Test fun punctuationCannotChangeEmissionLaggedTailOwner() {
        val raw = "可以听见我说话吗你好"
        for (text in listOf("可以听见我说话吗？你好。", "可以听见我说话吗你好。")) {
            val state = DiarizationTranscriptState()
            state.addUtterance(raw, text, raw.map { it.toString() },
                listOf(19700, 19740, 19820, 19900, 20020, 20140, 20300, 20460, 20660, 20860), 19700, 20860)
            state.applySpeakerTurns(listOf(turn(19600, 20652, "S1")))
            val before = state.allTurns()
            val result = state.sentenceUtterances().single()
            assertEquals("S1", result.speakerId)
            // Tail tokens 8 and 208 ms after the turn are emission lag, not missing coverage.
            assertFalse(result.speakerInferred)
            assertEquals(.8f, result.confidence)
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

    @Test fun emissionLaggedTailOfACleanSentenceIsDirectAttribution() {
        // Mate80 capture of the 19.58 s four-speaker clip: the final token is stamped
        // 268 ms after the speech turn, the first one 295 ms after its onset.
        val state = DiarizationTranscriptState()
        state.addUtterance("呃我是角色一", "呃，我是角色一。",
            listOf("▁ƌ", "Ĵ", "Ĥ", "▁ƍĩĴ", "▁ƍĻŕ", "▁Əōĵ", "▁ƏĪŘ", "▁ƋŞġ"),
            listOf(1440, 1480, 1520, 1680, 1920, 2080, 2240, 2560), 1440, 2560)
        state.applySpeakerTurns(listOf(turn(1145, 2292, "S1")))
        val before = state.allTurns()
        val result = state.sentenceUtterances().single()
        assertEquals("呃，我是角色一。", result.text)
        assertEquals("S1", result.speakerId)
        assertFalse("a clean single-speaker sentence must not be reported as inference", result.speakerInferred)
        assertEquals(.8f, result.confidence)
        assertEquals(before, state.allTurns())
    }

    @Test fun emissionLagAttributionIsCausalBoundedAndUnambiguous() {
        fun owners(times: List<Int>, turns: List<SpeakerTimelineTurn>) = DiarizationTranscriptState().run {
            addUtterance("甲乙", "甲乙。", listOf("甲", "乙"), times, times[0], times[1] + 100)
            applySpeakerTurns(turns)
            finalUtterances().map { it.speakerId to it.speakerInferred }
        }
        // Exactly at the measured 600 ms emission lag the tail is still this turn's speech.
        assertEquals(listOf("S1" to false), owners(listOf(100, 1100), listOf(turn(0, 500, "S1"))))
        // One millisecond beyond it, only the existing bounded backfill may infer the owner.
        assertEquals(listOf("S1" to true), owners(listOf(100, 1101), listOf(turn(0, 500, "S1"))))
        // UNKNOWN speech and ambiguous simultaneous ends never become direct owners.
        assertEquals(listOf("UNKNOWN"), owners(listOf(100, 600), listOf(turn(0, 500, "UNKNOWN"))).map { it.first })
        val ambiguous = DiarizationTranscriptState().apply {
            addUtterance("乙", "乙。", listOf("乙"), listOf(600), 600, 700)
            applySpeakerTurns(listOf(turn(0, 500, "S1"), turn(200, 500, "S2")))
        }
        assertEquals(listOf("UNKNOWN"), ambiguous.finalUtterances().map { it.speakerId })
        // Overlapped speech ends several voices at once: a known secondary blocks any owner,
        // and an unknown secondary leaves only the marked bounded backfill.
        assertEquals(listOf("S1" to false, "UNKNOWN" to false),
            owners(listOf(100, 600), listOf(turn(0, 500, "S1", listOf("S2")))))
        assertEquals(listOf("S1" to true),
            owners(listOf(100, 600), listOf(turn(0, 500, "S1", listOf("UNKNOWN_SECONDARY")))))
        // Emission is causal: a token before any speech is not given the following speaker directly.
        val leading = DiarizationTranscriptState().apply {
            addUtterance("甲", "甲。", listOf("甲"), listOf(100), 100, 150)
            applySpeakerTurns(listOf(turn(300, 800, "S1")))
        }
        assertTrue(leading.finalUtterances().all { it.speakerId != "S1" || it.speakerInferred })
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
