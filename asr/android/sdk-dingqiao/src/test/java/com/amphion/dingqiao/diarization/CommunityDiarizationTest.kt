package com.amphion.dingqiao.diarization

import org.junit.Assert.*
import org.junit.Test

class CommunityDiarizationTest {
    @Test fun boundedPullPreservesEveryWindowRegardlessOfInputFraming() {
        fun collect(chunks: List<Int>, capacity: Int): List<DiarizationInferenceWindow> {
            val scheduler = DiarizationWindowScheduler(16000, hopMs = 2000)
            val windows = mutableListOf<DiarizationInferenceWindow>()
            chunks.forEach { windows += scheduler.acceptSamples(it, capacity) }
            while (scheduler.hasAvailable()) windows += scheduler.takeAvailable(capacity)
            scheduler.finish()?.let { windows += it }
            return windows
        }
        val burst = collect(listOf(16000 * 61), 2)
        val framed = collect(List(3050) { 320 }, 1)
        assertEquals(burst, framed)
        assertEquals((0L..50L step 2).map { it * 16000 } + 52L * 16000, burst.map { it.startSample })
        assertEquals(61L * 16000, burst.last().realEndSample)
        assertTrue(burst.last().finalWindow)
        val exact = DiarizationWindowScheduler(16000, hopMs = 2000)
        exact.acceptSamples(16000 * 12)
        assertNull(exact.finish())
    }

    @Test fun identitySurvivesClusterRenumberingAndPreviewDoesNotEnroll() {
        val identity = CommunitySpeakerIdentity(4)
        fun assign(registry: CommunitySpeakerIdentity, ids: List<String>, labels: IntArray) =
            registry.assign(ids, labels, 2, IntArray(labels.size) { if (labels[it] >= 0) 10 else 0 }, booleanArrayOf(true, true))
        assertEquals(2, assign(identity.fork(), listOf("a", "b"), intArrayOf(0,-2,-2,1,-2,-2)).after)
        val first = assign(identity, listOf("a", "b"), intArrayOf(0,-2,-2,1,-2,-2))
        assertEquals(0, first.before)
        assertArrayEquals(intArrayOf(0,1), first.mapping)
        val swapped = assign(identity, listOf("b", "new", "a"), intArrayOf(0,-2,-2,1,-2,-2,1,-2,-2))
        assertArrayEquals(intArrayOf(1,0), swapped.mapping)
    }

    @Test fun newIdentitiesAreNumberedInAppearanceOrderWithoutRenamingCommittedOnes() {
        val identity = CommunitySpeakerIdentity(4)
        val activity = IntArray(6) { if (it % 3 == 0) 10 else 0 }
        // Cluster 1 speaks first on the timeline, so it receives the first public ID.
        val first = identity.assign(listOf("a", "b"), intArrayOf(0,-2,-2,1,-2,-2), 2, activity,
            booleanArrayOf(true, true), doubleArrayOf(5000.0, 1000.0))
        assertArrayEquals(intArrayOf(1, 0), first.mapping)
        // A later appearance order cannot rename identities that were already committed.
        val later = identity.assign(listOf("a", "b"), intArrayOf(0,-2,-2,1,-2,-2), 2, activity,
            booleanArrayOf(true, true), doubleArrayOf(0.0, 9000.0))
        assertArrayEquals(intArrayOf(1, 0), later.mapping)
    }

    @Test fun overlapAndUnknownRemainVisibleOnAbsoluteTimeline() {
        val turns = communityTimeline(listOf(doubleArrayOf(120000.0,123000.0,0.0),
            doubleArrayOf(121000.0,122000.0,-1.0)), intArrayOf(1),120000,124000)
        assertEquals(listOf(120000,121000,122000), turns.map { it.beginTime })
        assertEquals(listOf("S2","S2","S2"), turns.map { it.speakerId })
        assertEquals(listOf("UNKNOWN"), turns[1].secondarySpeakerIds)
        assertTrue(turns[1].overlap)
    }

    @Test fun replacementCanRetractPreviewButCannotChangeCommittedUtterances() {
        val transcript = DiarizationTranscriptState()
        transcript.addUtterance("你好", "你好。", listOf("你","好"),listOf(0,500),0,1000)
        transcript.applySpeakerTurns(listOf(SpeakerTimelineTurn(0,1000,"S1",emptyList())),true)
        assertEquals("S1", transcript.currentAssignment("u1")!!.speakerId)
        val correction = transcript.applySpeakerTurns(emptyList(),true)
        assertEquals("UNKNOWN", correction.single().speakerId)
        val frozen = transcript.commitThrough(1000)
        assertTrue(transcript.applySpeakerTurns(listOf(SpeakerTimelineTurn(0,1000,"S2",emptyList())),true).isEmpty())
        assertEquals("UNKNOWN", frozen.single().speakerId)
    }

    @Test fun punctuationSeparatesRealSpeakerChangeWithoutBreakingWords() {
        val transcript = DiarizationTranscriptState()
        transcript.addUtterance("你好张三", "你好，张三。", listOf("你","好","张","三"),listOf(0,500,1000,1500),0,2000)
        transcript.applySpeakerTurns(listOf(SpeakerTimelineTurn(0,1000,"S1",emptyList()),
            SpeakerTimelineTurn(1000,2000,"S2",emptyList())))
        val result = transcript.sentenceUtterances()
        assertEquals(listOf("你好，张三。"), result.map { it.text })
        assertEquals(listOf("UNKNOWN"), result.map { it.speakerId })
        assertTrue(result.all { it.sourceUtteranceId == "u1" })
    }

    @Test fun commitClockUsesCompletedAudioAndLastEndpointBeforeDeadline() {
        val clock = DiarizationCommitClock()
        clock.observeEndpoint(110000)
        assertFalse(clock.observeProcessedAudio(119999))
        assertNull(clock.takeReady(Int.MAX_VALUE))
        assertTrue(clock.observeProcessedAudio(120000))
        assertNull(clock.takeReady(122499))
        assertEquals(DiarizationCommitBoundary(0,110000,122500),clock.takeReady(122500))
    }
}
