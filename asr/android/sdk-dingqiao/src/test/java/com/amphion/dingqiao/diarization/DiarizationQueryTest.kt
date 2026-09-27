package com.amphion.dingqiao.diarization

import kotlin.math.sqrt
import org.junit.Assert.*
import org.junit.Test

class DiarizationQueryTest {
    @Test fun fixedOriginalReferencesRecoverDilutedCentroidWithoutCrossMatching() {
        fun v(d: Double) = floatArrayOf(kotlin.math.cos(d * Math.PI / 180).toFloat(),
            kotlin.math.sin(d * Math.PI / 180).toFloat())
        val r = OnlineSpeakerRegistry()
        r.assignBatch(listOf(v(0.0)), listOf(6000), 0)
        r.assignBatch(listOf(v(180.0)), listOf(6000), 0)
        r.bindComplementaryProfile("S1", listOf(v(-40.0), v(40.0)), listOf(3000, 3000))
        r.bindComplementaryProfile("S2", listOf(v(180.0)), listOf(3000))
        val p = v(60.0)
        val ids = setOf("S1", "S2")
        fun match(q: FloatArray = v(60.0), c: FloatArray = v(60.0)) =
            r.matchComplementaryQuery(p, p, q, c, ids)
        assertEquals("S1", match()?.speakerId)
        assertNull(match(v(60.0), v(-60.0)))
        assertNull(match(v(88.0), v(88.0)))
        assertEquals("S1", r.fork().matchComplementaryQuery(p, p, v(60.0), v(60.0), ids)?.speakerId)
        r.bindComplementaryProfile("S1", listOf(v(120.0)), listOf(6000))
        assertNull(match(v(120.0), v(120.0)))
        val bounded = OnlineSpeakerRegistry()
        bounded.assignBatch(listOf(v(0.0)), listOf(6000), 0)
        bounded.bindComplementaryProfile("S1", List(8) { v(0.0) } + listOf(v(90.0)), List(9) { 1000 })
        assertNull(bounded.matchComplementaryQuery(p, p, v(90.0), v(90.0), setOf("S1")))
    }

    @Test fun complementaryProfileIsFixedAndBothModelsMustAgree() {
        val r = OnlineSpeakerRegistry()
        r.assignBatch(listOf(floatArrayOf(1f, 0f)), listOf(6000), 0)
        r.assignBatch(listOf(floatArrayOf(-1f, 0f)), listOf(6000), 0)
        val weak = floatArrayOf(.52f, sqrt(1f - .52f * .52f))
        val strong = floatArrayOf(.7f, sqrt(1f - .7f * .7f))
        val ids = setOf("S1", "S2")
        assertNull(r.matchComplementaryQuery(weak, weak, strong, strong, ids))
        r.bindComplementaryProfile("S1", listOf(floatArrayOf(1f, 0f), floatArrayOf(1f, 0f)), listOf(1000, 2000))
        r.bindComplementaryProfile("S2", listOf(floatArrayOf(-1f, 0f)), listOf(3000))
        assertNull(r.matchQuery(weak, ids))
        assertEquals("S1", r.matchComplementaryQuery(weak, weak, strong, strong, ids)?.speakerId)
        assertEquals("S1", r.fork().matchComplementaryQuery(weak, weak, strong, strong, ids)?.speakerId)
        assertNull(r.matchComplementaryQuery(weak, floatArrayOf(-1f, 0f), strong, strong, ids))
        assertNull(r.matchComplementaryQuery(weak, weak, floatArrayOf(-1f, 0f), floatArrayOf(-1f, 0f), ids))
        assertNull(r.matchComplementaryQuery(weak, weak, floatArrayOf(.63f, sqrt(1f - .63f * .63f)), strong, ids))
        assertNull(r.matchComplementaryQuery(floatArrayOf(0f, 1f), floatArrayOf(0f, 1f), strong, strong, ids))
        assertNull(r.matchComplementaryQuery(weak, weak, strong, strong, emptySet()))
        r.bindComplementaryProfile("S1", listOf(floatArrayOf(-1f, 0f)), listOf(3000))
        assertEquals("S1", r.matchComplementaryQuery(weak, weak, strong, strong, ids)?.speakerId)
        assertEquals(listOf("S1", "S2"), r.speakerIds())
    }

    @Test fun independentContextSupportsOwnedSpeechWhenShortQueriesDiffer() {
        fun vector(degrees: Double) = Math.toRadians(degrees).let {
            floatArrayOf(kotlin.math.cos(it).toFloat(), kotlin.math.sin(it).toFloat())
        }
        fun assign(ownedDegrees: Double): OnlineSpeakerRegistry {
            val registry = OnlineSpeakerRegistry()
            registry.assignBatch(listOf(vector(0.0)), listOf(6000), 0)
            registry.assignBatch(listOf(vector(80.0)), listOf(6000), 10000,
                listOf(true), listOf(listOf(vector(ownedDegrees))),
                listOf(SpeakerIdentitySupport(vector(50.0), vector(35.0))))
            return registry
        }
        assertEquals(listOf("S1"), assign(90.0).speakerIds())
        assertEquals(listOf("S1", "S2"), assign(180.0).speakerIds())
        val supported = assign(90.0)
        assertEquals("S1", supported.matchQuietQuery(vector(80.0), vector(80.0), setOf("S1"))?.speakerId)
        assertEquals("S1", supported.fork().matchQuietQuery(vector(80.0), vector(80.0), setOf("S1"))?.speakerId)
        assertNull(supported.matchQuietQuery(vector(35.0), vector(50.0), setOf("S1")))
        assertNull(supported.matchQuietQuery(vector(180.0), vector(80.0), setOf("S1")))
        assertNull(supported.matchQuietQuery(vector(80.0), vector(80.0), emptySet()))
        assertEquals(listOf("S1"), supported.speakerIds())
    }

    @Test fun independentKnownQueryPreventsDuplicateWithoutChaining() {
        val first = floatArrayOf(1f, 0f, 0f, 0f)
        val changed = floatArrayOf(.55f, sqrt(1f - .55f * .55f), 0f, 0f)
        val y = (.64f - .55f * .64f) / changed[1]
        val bridge = floatArrayOf(.64f, y, sqrt(1f - .64f * .64f - y * y), 0f)
        val registry = OnlineSpeakerRegistry()
        registry.assignBatch(listOf(first), listOf(6000), 0)
        val matched = registry.assignBatch(listOf(changed), listOf(3200), 10000,
            listOf(true), listOf(listOf(changed)), listOf(SpeakerIdentitySupport(bridge, bridge))).single()
        assertEquals("S1", matched.speakerId)
        assertFalse(matched.created)
        assertEquals(listOf("S1"), registry.speakerIds())
        assertEquals("S1", registry.fork().matchQuery(changed, setOf("S1"))?.speakerId)
        assertNull(registry.matchKnown(changed))
        assertNull(registry.matchQuery(changed, emptySet()))
        val again = floatArrayOf(.1f, .7f, sqrt(.5f), 0f)
        assertEquals("S1", registry.assignBatch(listOf(again), listOf(3200), 20000,
            listOf(true), listOf(listOf(again))).single().speakerId)
        val next = floatArrayOf(0f, .45f, sqrt(1f - .45f * .45f), 0f)
        assertEquals("S2", registry.assignBatch(listOf(next), listOf(3200), 30000,
            listOf(true), listOf(listOf(next)), listOf(SpeakerIdentitySupport(again, again)))
            .single().speakerId)
    }

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

    @Test fun laterBoundaryPreservesGapsUnknownOverlapAndShortKnownChanges() {
        fun prepare(): DiarizationTranscriptState = DiarizationTranscriptState().apply {
            addUtterance("你好谢谢", "你好谢谢", listOf("你好", "谢谢"), listOf(1000, 4000), 1000, 6000)
            applySpeakerTurns(listOf(SpeakerTimelineTurn(1000, 2500, "S1", emptyList(), evidenceKey = "old"),
                SpeakerTimelineTurn(2700, 6000, "S1", emptyList(), evidenceKey = "old")))
        }
        val transcript = prepare()
        transcript.refineSingleSpeakerSpan(1000, 3000, 6000, "S2", "S1", .8f, .9f, emptyMap())
        transcript.applyEvidenceRemap(mapOf("old" to "S1"))
        assertEquals(listOf(Triple(1000, 2500, "S2"), Triple(2700, 3000, "S2"), Triple(3000, 6000, "S1")),
            transcript.allTurns().map { Triple(it.beginTime, it.endTime, it.speakerId) })
        val final = transcript.commitThrough(6000)
        assertEquals(listOf("你好谢谢" to "UNKNOWN"), final.map { it.text to it.speakerId })
        transcript.refineSingleSpeakerSpan(1000, 3000, 6000, "S1", "S2", 1f, 1f, emptyMap())
        assertEquals(listOf("UNKNOWN"), final.map { it.speakerId })
        for (extra in listOf(SpeakerTimelineTurn(2000, 2010, "S2", emptyList()),
            SpeakerTimelineTurn(2000, 2010, "UNKNOWN", emptyList()),
            SpeakerTimelineTurn(2000, 2010, "S1", listOf("UNKNOWN"), overlap = true))) {
            val other = prepare()
            other.applySpeakerTurns(listOf(extra))
            val before = other.allTurns()
            other.refineSingleSpeakerSpan(1000, 3000, 6000, "S2", "S1", .8f, .9f, emptyMap())
            assertEquals(before, other.allTurns())
        }
    }

    @Test fun quietLocalIdentityRequiresBothModelsAndCannotOverwriteKnownOrOverlap() {
        val a = floatArrayOf(1f, 0f)
        val b = floatArrayOf(0f, 1f)
        val registry = OnlineSpeakerRegistry()
        registry.assignBatch(listOf(a, b), listOf(6000, 6000), 0)
        registry.bindComplementaryProfile("S1", listOf(a), listOf(6000))
        registry.bindComplementaryProfile("S2", listOf(b), listOf(6000))
        val allowed = setOf("S1", "S2")
        assertEquals("S1", registry.matchLocalQuery(a, a, allowed)?.speakerId)
        assertNull(registry.matchLocalQuery(a, b, allowed))
        assertNull(registry.matchLocalQuery(floatArrayOf(1f, 1f), a, allowed))
        assertNull(registry.matchLocalQuery(a, a, emptySet()))
        assertEquals(listOf("S1", "S2"), registry.speakerIds())
        val transcript = DiarizationTranscriptState()
        transcript.applySpeakerTurns(listOf(
            SpeakerTimelineTurn(0, 250, "S2", emptyList(), evidenceKey = "q"),
            SpeakerTimelineTurn(250, 500, "UNKNOWN", listOf("UNKNOWN"), overlap = true, evidenceKey = "q"),
            SpeakerTimelineTurn(500, 1000, "UNKNOWN", emptyList(), evidenceKey = "q")))
        transcript.resolveUnknownSpan("q", 0, 750, "S1", .8f, emptyMap())
        assertEquals(listOf(Triple(0, 250, "S2"), Triple(250, 500, "UNKNOWN"),
            Triple(500, 750, "S1"), Triple(750, 1000, "UNKNOWN")),
            transcript.allTurns().map { Triple(it.beginTime, it.endTime, it.speakerId) })
        transcript.commitThrough(1000)
        transcript.resolveUnknownSpan("q", 0, 1000, "S2", 1f, emptyMap())
        assertTrue(transcript.allTurns().isEmpty())
    }
}
