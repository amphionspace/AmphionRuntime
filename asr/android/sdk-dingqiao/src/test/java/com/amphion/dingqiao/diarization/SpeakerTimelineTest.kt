package com.amphion.dingqiao.diarization

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** 对齐鸿蒙 `SpeakerTimeline.ts` 与 test_harmony_sortformer_diarization.py 的同一组期望。 */
class SpeakerTimelineTest {
    private fun shape(turns: List<SpeakerTimelineTurn>) =
        turns.map { listOf(it.beginTime, it.endTime, it.speakerId, it.overlap) }

    @Test
    fun concurrentTracksBecomeANonOverlappingTimelineAndKeepOverlapFlags() {
        // 槽位 1 先开口（角色 0），槽位 0 接话（角色 1），4000~4500 两人重叠
        val tracks = listOf(
            SortformerTrack(0, 4_500, slot = 1),
            SortformerTrack(4_000, 9_920, slot = 0),
        )
        val turns = timelineTurns(tracks, intArrayOf(1, 0, -1, -1), 0, 9_920)
        assertEquals(
            listOf(
                listOf(0, 4_000, "S1", false),
                listOf(4_000, 4_500, "S1", true),
                listOf(4_500, 9_920, "S2", false),
            ),
            shape(turns),
        )
        // 重叠段里另一个人进 secondary，没有轨道被丢掉
        assertEquals(listOf("S2"), turns[1].secondarySpeakerIds)
    }

    @Test
    fun anUnconfirmedSlotIsUnknownNotADroppedTrack() {
        val tracks = listOf(
            SortformerTrack(0, 2_000, slot = 0),
            SortformerTrack(2_000, 4_000, slot = 2),
        )
        val turns = timelineTurns(tracks, intArrayOf(0, -1, -1, -1), 0, 4_000)
        assertEquals(listOf("S1", "UNKNOWN"), turns.map { it.speakerId })
    }

    @Test
    fun silenceSplitsTurnsInsteadOfMergingAcrossIt() {
        val tracks = listOf(
            SortformerTrack(0, 1_000, slot = 0),
            SortformerTrack(3_000, 4_000, slot = 0),
        )
        val turns = timelineTurns(tracks, intArrayOf(0, -1, -1, -1), 0, 4_000)
        assertEquals(
            listOf(listOf(0, 1_000, "S1", false), listOf(3_000, 4_000, "S1", false)),
            shape(turns),
        )
    }

    @Test
    fun adjacentSegmentsOfTheSameSpeakerCoalesce() {
        val tracks = listOf(
            SortformerTrack(0, 1_000, slot = 0),
            SortformerTrack(1_000, 2_000, slot = 0),
        )
        val turns = timelineTurns(tracks, intArrayOf(0, -1, -1, -1), 0, 2_000)
        assertEquals(1, turns.size)
        assertEquals(0 to 2_000, turns[0].beginTime to turns[0].endTime)
    }

    @Test
    fun theRangeClipsTracksOnBothSides() {
        val tracks = listOf(SortformerTrack(0, 9_920, slot = 0))
        val turns = timelineTurns(tracks, intArrayOf(0, -1, -1, -1), 2_000, 5_000)
        assertEquals(listOf(listOf(2_000, 5_000, "S1", false)), shape(turns))
    }

    @Test
    fun thePrimarySpeakerPrefersContinuityAcrossBoundaries() {
        // S2 独占 0~1000，然后 S1 与 S2 重叠：主说话人延续 S2 而不是按字典序取 S1
        val tracks = listOf(
            SortformerTrack(0, 3_000, slot = 1),
            SortformerTrack(1_000, 3_000, slot = 0),
        )
        val turns = timelineTurns(tracks, intArrayOf(1, 0, -1, -1), 0, 3_000)
        assertEquals("S1", turns[0].speakerId)
        assertEquals("S1", turns[1].speakerId)
        assertTrue(turns[1].overlap)
        assertEquals(listOf("S2"), turns[1].secondarySpeakerIds)
    }

    @Test
    fun noTracksMeansNoTurns() {
        assertTrue(timelineTurns(emptyList(), intArrayOf(-1, -1, -1, -1), 0, 9_920).isEmpty())
    }
}
