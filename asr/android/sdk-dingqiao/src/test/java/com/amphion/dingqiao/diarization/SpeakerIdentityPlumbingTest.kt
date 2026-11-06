package com.amphion.dingqiao.diarization

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 声纹身份穿过时间线与转写状态的接线。对齐鸿蒙
 * test_model_speaker_id_survives_the_transcript_state / test_model_speaker_index_is_exposed_on_speaker_turns_only。
 */
class SpeakerIdentityPlumbingTest {
    @Test
    fun perTrackIdentityOverridesTheSlotMappingAndKeepsTheModelsOwnAnswer() {
        // 两段同在槽位 0（模型把两个人并成了一个），声纹把它们分成身份 0 和 1
        val tracks = listOf(
            SortformerTrack(0, 2_000, slot = 0, identity = 0),
            SortformerTrack(2_000, 4_000, slot = 0, identity = 1),
        )
        val turns = timelineTurns(tracks, intArrayOf(0, -1, -1, -1), 0, 4_000)
        assertEquals(listOf("S1", "S2"), turns.map { it.speakerId })
        assertEquals("模型自己的判断仍是同一个槽位", listOf("S1", "S1"), turns.map { it.modelSpeakerId })
        // 相邻两段 speakerId 不同，所以不能合并
        assertEquals(2, turns.size)
    }

    @Test
    fun unresolvedIdentityIsUnknownNotAGuess() {
        val tracks = listOf(SortformerTrack(0, 2_000, slot = 0, identity = SpeakerIdentityResolver.UNRESOLVED))
        val turns = timelineTurns(tracks, intArrayOf(0, -1, -1, -1), 0, 2_000)
        assertEquals("UNKNOWN", turns.single().speakerId)
        assertEquals("模型侧照常给出槽位身份", "S1", turns.single().modelSpeakerId)
    }

    @Test
    fun withoutIdentityTheTimelineIsUnchangedAndModelIdEqualsSpeakerId() {
        val tracks = listOf(SortformerTrack(0, 2_000, slot = 1), SortformerTrack(2_000, 4_000, slot = 0))
        val turns = timelineTurns(tracks, intArrayOf(1, 0, -1, -1), 0, 4_000)
        assertEquals(listOf("S1", "S2"), turns.map { it.speakerId })
        assertEquals(turns.map { it.speakerId }, turns.map { it.modelSpeakerId })
    }

    @Test
    fun adjacentTurnsMergeOnlyWhenTheModelSpeakerIdAlsoMatches() {
        // 同一声纹身份跨两个槽位：speakerId 相同但 modelSpeakerId 不同，不能合成一段
        val tracks = listOf(
            SortformerTrack(0, 2_000, slot = 0, identity = 0),
            SortformerTrack(2_000, 4_000, slot = 1, identity = 0),
        )
        val turns = timelineTurns(tracks, intArrayOf(0, 1, -1, -1), 0, 4_000)
        assertEquals(listOf("S1", "S1"), turns.map { it.speakerId })
        assertEquals(listOf("S1", "S2"), turns.map { it.modelSpeakerId })
        assertEquals(2, turns.size)
        // 两者都相同时照常合并
        val same = timelineTurns(
            listOf(SortformerTrack(0, 2_000, 0, 0), SortformerTrack(2_000, 4_000, 0, 0)),
            intArrayOf(0, -1, -1, -1), 0, 4_000,
        )
        assertEquals(1, same.size)
        assertEquals(4_000, same.single().endTime)
    }

    @Test
    fun modelSpeakerIdSurvivesTheTranscriptState() {
        val state = DiarizationTranscriptState()
        state.addUtterance("你好", "你好。", listOf("你", "好"), listOf(0, 500), 0, 1_000)
        state.applySpeakerTurns(listOf(SpeakerTimelineTurn(0, 1_000, "S2", emptyList(), modelSpeakerId = "S1")), true)
        val turn = state.allTurns().single()
        assertEquals("S2", turn.speakerId)
        assertEquals("allTurns() 不能丢 modelSpeakerId（鸿蒙踩过的 bug）", "S1", turn.modelSpeakerId)
        // 没带模型身份的 turn 保持 null，公开层据此报 -1 而不是回落到 speakerId
        state.applySpeakerTurns(listOf(SpeakerTimelineTurn(0, 1_000, "S2", emptyList())), true)
        assertNull(state.allTurns().single().modelSpeakerId)
    }
}
