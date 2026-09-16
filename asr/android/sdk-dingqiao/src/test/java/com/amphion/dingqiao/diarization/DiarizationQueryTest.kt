package com.amphion.dingqiao.diarization

import kotlin.math.sqrt
import org.junit.Assert.*
import org.junit.Test

class DiarizationQueryTest {
    @Test fun uncertaintyDoesNotEnrollAnotherIdentity() {
        val registry = OnlineSpeakerRegistry()
        fun assign(vararg values: Float) = registry.assignBatch(listOf(values), listOf(2000), 0).single()
        assertEquals("S1", assign(1f, 0f, 0f).speakerId)
        assertEquals("UNKNOWN", assign(.68f, kotlin.math.sqrt(1f - .68f * .68f), 0f).speakerId)
        assertEquals(listOf("S1"), registry.speakerIds())
        assertEquals("S2", assign(0f, 1f, 0f).speakerId)
        assertEquals("UNKNOWN", assign(1f, 1f, 0f).speakerId)
        assertEquals(listOf("S1", "S2"), registry.speakerIds())
        assertEquals("S1", assign(.9f, 0f, kotlin.math.sqrt(.19f)).speakerId)
    }

    @Test
    fun shortQueryMatchesEstablishedRoleWithoutChangingItsProfile() {
        val registry = OnlineSpeakerRegistry()
        registry.assignBatch(listOf(floatArrayOf(1f, 0f, 0f), floatArrayOf(0f, 1f, 0f)), listOf(6000, 6000), 0)
        val query = floatArrayOf(.63f, .41f, sqrt(1f - .63f * .63f - .41f * .41f))
        val ids = setOf("S1", "S2")
        assertNull(registry.matchKnown(query))
        val matched = checkNotNull(registry.matchQuery(query, ids))
        assertEquals("S1", matched.speakerId)
        assertEquals(.63f, matched.confidence, 1e-6f)
        assertFalse(matched.created)
        assertEquals(matched, registry.matchQuery(query, ids))
        assertEquals(listOf("S1", "S2"), registry.speakerIds())
        assertNull(registry.matchQuery(floatArrayOf(.67f, .67f, sqrt(1f - 2 * .67f * .67f)), ids))
        assertNull(registry.matchQuery(floatArrayOf(-1f, 0f, 0f), ids))
    }

    @Test
    fun queryCannotIntroduceContextOnlyIdentity() {
        val registry = OnlineSpeakerRegistry()
        val query = floatArrayOf(.693f, 0f, sqrt(1f - .693f * .693f))
        registry.assignBatch(listOf(floatArrayOf(-1f, 0f, 0f), floatArrayOf(1f, 0f, 0f), query),
            listOf(6000, 6000, 1076), 0)
        assertEquals("S3", registry.matchKnown(query))
        assertEquals("S2", registry.matchQuery(query, setOf("S1", "S2"))?.speakerId)
        assertNull(registry.matchQuery(query, emptySet()))
        assertEquals(listOf("S1", "S2", "S3"), registry.speakerIds())
    }

    @Test
    fun correctedConfidenceIsFrozenWithItsUtterance() {
        val transcript = DiarizationTranscriptState()
        transcript.addUtterance("甲", "甲", listOf("甲"), listOf(100), 0, 1000)
        transcript.applySpeakerTurns(listOf(SpeakerTimelineTurn(0, 1000, "S2", emptyList(), 1f, evidenceKey = "query")))
        transcript.applyEvidenceRemap(mapOf("query" to "S1"), confidences = mapOf("query" to .63f))
        val published = transcript.commitThrough(1000).single()
        assertEquals("S1", published.speakerId)
        assertEquals(.63f, published.confidence, 1e-6f)
        assertTrue(transcript.applyEvidenceRemap(mapOf("query" to "S2"), confidences = mapOf("query" to 1f)).isEmpty())
        assertEquals(.63f, published.confidence, 1e-6f)
    }
}
