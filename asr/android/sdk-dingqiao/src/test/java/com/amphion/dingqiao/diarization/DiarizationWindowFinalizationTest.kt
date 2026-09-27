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
    @Test fun oneMixedAnchorCannotCommitADifferentSpeakerCluster() {
        for ((speakerAngle, mixedAngle) in listOf(65 to 43, 30 to 10, 50 to 43))
            mockConstruction(SpeakerDiarizationLocalClient::class.java).use {
            val newPerson = speakerAngle == 65
            val directory = Files.createTempDirectory("diarization-anchor-consensus").toFile()
            val session = SpeakerDiarizationSession(mock<Context>(), directory, 4,
                object : SpeakerDiarizationSessionObserver {
                    override fun onUpdate(update: SpeakerDiarizationUpdate) = Unit
                    override fun onFinished(result: SpeakerDiarizationResult) = Unit
                })
            try {
                fun vector(degrees: Int) = floatArrayOf(
                    kotlin.math.cos(degrees * Math.PI / 180).toFloat(),
                    kotlin.math.sin(degrees * Math.PI / 180).toFloat())
                val committed = session.javaClass.getDeclaredField("committedRegistry")
                    .apply { isAccessible = true }.get(session) as OnlineSpeakerRegistry
                committed.assignBatch(listOf(vector(0)), listOf(6000), 0)
                session.javaClass.getDeclaredField("registry").apply { isAccessible = true }
                    .set(session, committed.fork())
                @Suppress("UNCHECKED_CAST")
                val published = session.javaClass.getDeclaredField("publishedSpeakerIds")
                    .apply { isAccessible = true }.get(session) as MutableSet<String>
                published.add("S1")
                session.append(ByteArray(30_000 * 32))
                repeat(5) { i ->
                    val begin = i * 96000L
                    val owned = vector(speakerAngle)
                    val context = if (i == 4) vector(mixedAngle) else owned
                    session.onWindow(DiarizationLocalWindowResult("w$i", begin, 0,
                        begin + 96000, begin, begin + 96000, false, DiarizationWindowInferenceResult(
                            listOf(SpeakerSegmentationSegment(0, 96000, 0, 1, owned)),
                            listOf(DiarizationEmbedding(0, 96000, context, owned, .1)), 0)))
                }
                val commit = session.javaClass.getDeclaredMethod("commitWindowLocked", Int::class.javaPrimitiveType,
                    Int::class.javaPrimitiveType, Boolean::class.javaPrimitiveType, Int::class.javaPrimitiveType)
                    .apply { isAccessible = true }
                val result = commit.invoke(session, 30000, Int.MAX_VALUE, true, 0) as SpeakerDiarizationResult
                assertEquals(if (newPerson) 2 else 1, result.speakerCount)
                assertTrue(result.speakerTurns.all { it.speakerIndex == if (newPerson) 1 else 0 })
                assertEquals("S1", committed.matchKnown(vector(0)))
            } finally { session.cancel(); directory.deleteRecursively() }
        }
    }

    @Test fun independentOutputQueriesPreserveTheSecondPersonAtFinalization() {
        for (queryCount in listOf(2, 1)) mockConstruction(SpeakerDiarizationLocalClient::class.java).use {
            val directory = Files.createTempDirectory("diarization-query-consensus").toFile()
            val results = mutableListOf<SpeakerDiarizationResult>()
            val session = SpeakerDiarizationSession(mock<Context>(), directory, 4,
                object : SpeakerDiarizationSessionObserver {
                    override fun onUpdate(update: SpeakerDiarizationUpdate) = Unit
                    override fun onFinished(result: SpeakerDiarizationResult) { results += result }
                })
            try {
                session.append(ByteArray(640000))
                val context = floatArrayOf(.61f, kotlin.math.sqrt(1f - .61f * .61f))
                val query = floatArrayOf(.45f, kotlin.math.sqrt(1f - .45f * .45f))
                for (i in 0..3) {
                    val begin = i * 80000L
                    val embedding = if (i < 2) floatArrayOf(1f, 0f) else context
                    val owned = if (i < 2) embedding else if (i - 2 < queryCount) query else null
                    session.onWindow(DiarizationLocalWindowResult("w$i", begin, 0,
                        begin + 80000, begin, begin + 80000, false, DiarizationWindowInferenceResult(
                            listOf(SpeakerSegmentationSegment(0, 80000, 0, 1)),
                            listOf(DiarizationEmbedding(0, if (i < 2) 80000 else 64000,
                                embedding, owned, .1)), 0)))
                }
                session.finish()
                session.observeAsrFinal(SpeechRecognitionResult(isFinal = true, isLast = true), AsrResult("", isLast = true))
                session.onDrained()
                assertEquals(if (queryCount == 2) 2 else 1, results.single().speakerCount)
                assertEquals(if (queryCount == 2) listOf(0, 0, 1, 1) else listOf(0, 0, -1, -1),
                    results.single().speakerTurns.map { it.speakerIndex })
            } finally { session.cancel(); directory.deleteRecursively() }
        }
    }

    @Test fun separateRunsOnOneChannelUseTheirOwnQueryAcrossACommitBoundary() {
        mockConstruction(SpeakerDiarizationLocalClient::class.java).use {
            val directory = Files.createTempDirectory("diarization-run-query").toFile()
            val session = SpeakerDiarizationSession(mock<Context>(), directory, 4,
                object : SpeakerDiarizationSessionObserver {
                    override fun onUpdate(update: SpeakerDiarizationUpdate) = Unit
                    override fun onFinished(result: SpeakerDiarizationResult) = Unit
                })
            try {
                session.append(ByteArray(320000))
                val committed = session.javaClass.getDeclaredField("committedRegistry")
                    .apply { isAccessible = true }.get(session) as OnlineSpeakerRegistry
                committed.assignBatch(listOf(floatArrayOf(1f, 0f), floatArrayOf(0f, 1f)), listOf(6000, 6000), 0)
                session.javaClass.getDeclaredField("registry").apply { isAccessible = true }.set(session, committed.fork())
                @Suppress("UNCHECKED_CAST")
                val published = session.javaClass.getDeclaredField("publishedSpeakerIds")
                    .apply { isAccessible = true }.get(session) as MutableSet<String>
                published.addAll(listOf("S1", "S2"))
                session.onWindow(DiarizationLocalWindowResult("mixed-channel", 0, 0, 160000, 0, 160000, true,
                    DiarizationWindowInferenceResult(listOf(
                        SpeakerSegmentationSegment(0, 32000, 0, 1, floatArrayOf(1f, 0f)),
                        SpeakerSegmentationSegment(64000, 96000, 0, 1, floatArrayOf(0f, 1f))),
                        listOf(DiarizationEmbedding(0, 64000, floatArrayOf(1f, 0f), floatArrayOf(1f, 0f), .1)), 0)))
                val commit = session.javaClass.getDeclaredMethod("commitWindowLocked", Int::class.javaPrimitiveType,
                    Int::class.javaPrimitiveType, Boolean::class.javaPrimitiveType, Int::class.javaPrimitiveType)
                    .apply { isAccessible = true }
                val first = commit.invoke(session, 3000, 10000, false, 0) as SpeakerDiarizationResult
                val second = commit.invoke(session, 10000, Int.MAX_VALUE, true, 3000) as SpeakerDiarizationResult
                assertEquals(listOf(0), first.speakerTurns.map { it.speakerIndex })
                assertEquals(listOf(1), second.speakerTurns.map { it.speakerIndex })
                assertEquals(2, committed.speakerIds().size)
            } finally { session.cancel(); directory.deleteRecursively() }
        }
    }

    @Test fun contextOnlyCandidateLeavesCapacityForASupportedFourthSpeaker() {
        mockConstruction(SpeakerDiarizationLocalClient::class.java).use {
            val directory = Files.createTempDirectory("diarization-fourth-speaker-test").toFile()
            val results = mutableListOf<SpeakerDiarizationResult>()
            val observer = object : SpeakerDiarizationSessionObserver {
                override fun onUpdate(update: SpeakerDiarizationUpdate) = Unit
                override fun onFinished(result: SpeakerDiarizationResult) { results += result }
            }
            val session = SpeakerDiarizationSession(mock<Context>(), directory, 4, observer)
            try {
                session.append(ByteArray(320000))
                fun vector(index: Int) = FloatArray(5) { if (it == index) 1f else 0f }
                val committed = session.javaClass.getDeclaredField("committedRegistry")
                    .apply { isAccessible = true }.get(session) as OnlineSpeakerRegistry
                committed.assignBatch((0..2).map(::vector), listOf(6000, 6000, 6000), 0)
                session.javaClass.getDeclaredField("registry").apply { isAccessible = true }
                    .set(session, committed.fork())
                fun window(id: String, begin: Int, end: Int, contextBegin: Int,
                           index: Int, hasQuery: Boolean) {
                    session.onWindow(DiarizationLocalWindowResult(id, 0, 0, 160000,
                        begin * 16L, end * 16L, false, DiarizationWindowInferenceResult(
                            listOf(SpeakerSegmentationSegment(contextBegin * 16, end * 16, 0, 1)),
                            listOf(DiarizationEmbedding(0, (end - contextBegin) * 16, vector(index),
                                if (hasQuery) vector(index) else null, speechRms = 0.1)), 0)))
                }
                // A longer historical mixture must not take the last available identity.
                window("mixed-context", 4000, 4600, 1000, 3, false)
                window("fourth-person", 4600, 7800, 4600, 4, true)
                session.finish()
                session.observeAsrFinal(SpeechRecognitionResult(isFinal = true, isLast = true),
                    AsrResult("", isLast = true))
                session.onDrained()
                assertEquals(listOf(-1, 3), results.single().speakerTurns.map { it.speakerIndex })
                assertEquals(4, results.single().speakerCount)
                assertEquals(listOf("S1", "S2", "S3", "S4"), committed.speakerIds())
            } finally {
                session.cancel()
                directory.deleteRecursively()
            }
        }
    }

    @Test fun contextWithoutOutputQueryCannotEnrollOrRedirectAnotherSpeaker() {
        mockConstruction(SpeakerDiarizationLocalClient::class.java).use {
            val directory = Files.createTempDirectory("diarization-query-enrollment-test").toFile()
            val results = mutableListOf<SpeakerDiarizationResult>()
            val observer = object : SpeakerDiarizationSessionObserver {
                override fun onUpdate(update: SpeakerDiarizationUpdate) = Unit
                override fun onFinished(result: SpeakerDiarizationResult) { results += result }
            }
            val session = SpeakerDiarizationSession(mock<Context>(), directory, 4, observer)
            try {
                session.append(ByteArray(640000))
                val committed = session.javaClass.getDeclaredField("committedRegistry")
                    .apply { isAccessible = true }.get(session) as OnlineSpeakerRegistry
                committed.assignBatch(listOf(floatArrayOf(1f, 0f, 0f)), listOf(6000), 0)
                val voice = floatArrayOf(0f, 1f, 0f)
                val query = floatArrayOf(kotlin.math.sqrt(1f - .57f * .57f - .636f * .636f), .57f, .636f)
                fun window(id: String, begin: Int, end: Int, contextBegin: Int,
                           embedding: FloatArray, outputQuery: FloatArray?) {
                    session.onWindow(DiarizationLocalWindowResult(id, 0, 0, 320000,
                        begin * 16L, end * 16L, false, DiarizationWindowInferenceResult(
                            listOf(SpeakerSegmentationSegment(contextBegin * 16, end * 16, 0, 1)),
                            listOf(DiarizationEmbedding(0, (end - contextBegin) * 16, embedding,
                                outputQuery, speechRms = 0.1)), 0)))
                }
                window("supported", 6000, 10000, 6000, voice, voice)
                window("query", 10000, 12000, 8000, voice, query)
                window("mixed-context", 12000, 12673, 9163, floatArrayOf(0f, 0f, 1f), null)
                session.finish()
                session.observeAsrFinal(SpeechRecognitionResult(isFinal = true, isLast = true),
                    AsrResult("", isLast = true))
                session.onDrained()
                assertEquals(listOf(1, 1, -1), results.single().speakerTurns.map { it.speakerIndex })
                assertEquals(2, results.single().speakerCount)
            } finally {
                session.cancel()
                directory.deleteRecursively()
            }
        }
    }

    @Test fun repeatedShortContextCannotEnrollButCanRecognizeAnExistingSpeaker() {
        mockConstruction(SpeakerDiarizationLocalClient::class.java).use {
            fun run(embedding: FloatArray, speechMs: Int, seedMs: Int = 6000,
                    speechSamples: Int = speechMs * 16): Pair<List<String>, SpeakerDiarizationResult> {
                val directory = Files.createTempDirectory("diarization-short-enrollment-test").toFile()
                val results = mutableListOf<SpeakerDiarizationResult>()
                val observer = object : SpeakerDiarizationSessionObserver {
                    override fun onUpdate(update: SpeakerDiarizationUpdate) = Unit
                    override fun onFinished(result: SpeakerDiarizationResult) { results += result }
                }
                val session = SpeakerDiarizationSession(mock<Context>(), directory, 4, observer)
                try {
                    session.append(ByteArray(448000))
                    for (index in 0..4) {
                        val start = if (index == 0) 0 else 7000
                        val durationSamples = if (index == 0) seedMs * 16 else speechSamples
                        val vector = if (index == 0) floatArrayOf(1f, 0f) else embedding
                        session.onWindow(DiarizationLocalWindowResult("w$index", 0, 0, 224000,
                            if (index < 2) 0 else 176000, 224000, false,
                            DiarizationWindowInferenceResult(listOf(
                                SpeakerSegmentationSegment(start * 16, start * 16 + durationSamples, 0, 1)),
                                listOf(DiarizationEmbedding(0, durationSamples, vector,
                                    if (index < 2) vector else null, speechRms = 0.1)), 0)))
                    }
                    val registry = session.javaClass.getDeclaredField("registry")
                        .apply { isAccessible = true }.get(session) as OnlineSpeakerRegistry
                    val provisional = registry.speakerIds()
                    session.finish()
                    session.observeAsrFinal(SpeechRecognitionResult(isFinal = true, isLast = true),
                        AsrResult("", isLast = true))
                    session.onDrained()
                    return provisional to results.single()
                } finally {
                    session.cancel()
                    directory.deleteRecursively()
                }
            }
            val first = run(floatArrayOf(1f, 0f), 1200, 1200)
            assertEquals(listOf("S1"), first.first)
            assertEquals(1, first.second.speakerCount)
            assertEquals(1, run(floatArrayOf(0f, 1f), 2999).second.speakerCount)
            assertEquals(1, run(floatArrayOf(0f, 1f), 3000, speechSamples = 47999).second.speakerCount)
            val short = run(floatArrayOf(.53f, kotlin.math.sqrt(1f - .53f * .53f)), 1200)
            assertEquals(listOf("S1"), short.first)
            assertEquals(1, short.second.speakerCount)
            assertEquals(listOf(0, -1), short.second.speakerTurns.map { it.speakerIndex })
            val known = run(floatArrayOf(1f, 0f), 1200)
            assertEquals(listOf(0, 0), known.second.speakerTurns.map { it.speakerIndex })
            val distinct = run(floatArrayOf(0f, 1f), 3000)
            assertEquals(listOf("S1", "S2"), distinct.first)
            assertEquals(listOf(0, 1), distinct.second.speakerTurns.map { it.speakerIndex }.sorted())
        }
    }

    @Test fun hiddenSecondaryKeepsItsEvidenceBindingAcrossPartialRemaps() {
        val transcript = DiarizationTranscriptState()
        transcript.applySpeakerTurns(listOf(SpeakerTimelineTurn(0, 2000, "S1", listOf("S2", "S3"),
            evidenceKey = "a", secondaryEvidenceKeys = listOf("b", "c"))))
        transcript.applyEvidenceRemap(mapOf("a" to "S1", "b" to "S1", "c" to "S3"))
        assertEquals(listOf("S3"), transcript.allTurns().single().secondarySpeakerIds)
        transcript.applyEvidenceRemap(mapOf("b" to "S2"))
        assertEquals(listOf("S2", "S3"), transcript.allTurns().single().secondarySpeakerIds)
    }

    @Test fun provisionalUnknownCollisionCannotEraseFinalOverlap() {
        mockConstruction(SpeakerDiarizationLocalClient::class.java).use {
            val directory = Files.createTempDirectory("diarization-overlap-evidence-test").toFile()
            val results = mutableListOf<SpeakerDiarizationResult>()
            val observer = object : SpeakerDiarizationSessionObserver {
                override fun onUpdate(update: SpeakerDiarizationUpdate) = Unit
                override fun onWindowResult(result: SpeakerDiarizationResult) = Unit
                override fun onFinished(result: SpeakerDiarizationResult) { results += result }
            }
            val session = SpeakerDiarizationSession(mock<Context>(), directory, 4, observer)
            try {
                val registry = session.javaClass.getDeclaredField("registry")
                    .apply { isAccessible = true }.get(session) as OnlineSpeakerRegistry
                fun vector(index: Int) = FloatArray(6) { if (it == index) 1f else 0f }
                registry.assignBatch((0..3).map { vector(it) }, List(4) { 2000 }, 0)
                session.append(ByteArray(307200))
                session.onWindow(DiarizationLocalWindowResult("overlap", 0, 0, 153600, 0,
                    153600, true, DiarizationWindowInferenceResult(
                        listOf(SpeakerSegmentationSegment(0, 51200, 0, 1),
                            SpeakerSegmentationSegment(51200, 102400, 1, 2),
                            SpeakerSegmentationSegment(102400, 153600, 0, 3)),
                        listOf(DiarizationEmbedding(0, 51200, vector(4), vector(4), speechRms = 0.1),
                            DiarizationEmbedding(1, 51200, vector(5), vector(5), speechRms = 0.1)), 0)))
                session.finish()
                session.observeAsrFinal(SpeechRecognitionResult(isFinal = true, isLast = true),
                    AsrResult("", isLast = true))
                session.onDrained()
                assertEquals(0, results.single().speakerTurns.last().speakerIndex)
                assertEquals(listOf(1), results.single().speakerTurns.last().secondarySpeakerIndexes)
            } finally {
                session.cancel()
                directory.deleteRecursively()
            }
        }
    }

    @Test fun historicalContextCannotCompeteWithCurrentSpeech() {
        mockConstruction(SpeakerDiarizationLocalClient::class.java).use {
            val directory = Files.createTempDirectory("diarization-owned-speech-test").toFile()
            val observer = object : SpeakerDiarizationSessionObserver {
                override fun onUpdate(update: SpeakerDiarizationUpdate) = Unit
                override fun onWindowResult(result: SpeakerDiarizationResult) = Unit
                override fun onFinished(result: SpeakerDiarizationResult) = Unit
            }
            val session = SpeakerDiarizationSession(mock<Context>(), directory, 4, observer)
            try {
                session.onWindow(window(4000))
                val current = floatArrayOf(.767f, kotlin.math.sqrt(1f - .767f * .767f))
                session.onWindow(DiarizationLocalWindowResult("current", 0, 0, 160000, 96000,
                    136000, false, DiarizationWindowInferenceResult(listOf(
                        SpeakerSegmentationSegment(32000, 96000, 0, 1),
                        SpeakerSegmentationSegment(121600, 160000, 1, 2)), listOf(
                        DiarizationEmbedding(0, 32000, floatArrayOf(1f, 0f), speechRms = 0.1),
                        DiarizationEmbedding(1, 38400, current, speechRms = 0.1)), 0)))
                val transcript = session.javaClass.getDeclaredField("transcript")
                    .apply { isAccessible = true }.get(session) as DiarizationTranscriptState
                assertEquals(listOf("S1"), transcript.allTurns()
                    .filter { it.beginTime >= 6000 }.map { it.speakerId })
                val observations = session.javaClass.getDeclaredField("recentObservations")
                    .apply { isAccessible = true }.get(session) as List<*>
                assertEquals("context remains available for final clustering", 3, observations.size)
            } finally {
                session.cancel()
                directory.deleteRecursively()
            }
        }
    }

    @Test fun windowPublicationCannotOvertakeAnEarlierUpdateDuringConcurrentDrain() {
        mockConstruction(SpeakerDiarizationLocalClient::class.java).use {
            val updating = CountDownLatch(1)
            val releaseUpdate = CountDownLatch(1)
            val results = java.util.concurrent.CopyOnWriteArrayList<SpeakerDiarizationResult>()
            val observer = object : SpeakerDiarizationSessionObserver {
                override fun onUpdate(update: SpeakerDiarizationUpdate) {
                    updating.countDown()
                    assertTrue(releaseUpdate.await(3, TimeUnit.SECONDS))
                }
                override fun onWindowResult(result: SpeakerDiarizationResult) { results += result }
                override fun onFinished(result: SpeakerDiarizationResult) = Unit
            }
            val directory = Files.createTempDirectory("diarization-order-test").toFile()
            val session = SpeakerDiarizationSession(mock<Context>(), directory, 4, observer)
            val final = AsrResult("词")
            ResultAudioTimeline.record(final, 120000 * 16L)
            session.observeAsrFinal(SpeechRecognitionResult(isFinal = true, result = "词",
                beginTime = 111000, endTime = 119000), final)
            session.asrFinalDelivered(final)
            val executor = Executors.newSingleThreadExecutor()
            try {
                val pending = executor.submit { session.onWindow(window(122500)) }
                assertTrue(updating.await(3, TimeUnit.SECONDS))
                session.asrFinalDelivered(final)
                assertTrue("window result overtook an earlier update", results.isEmpty())
                releaseUpdate.countDown()
                pending.get(3, TimeUnit.SECONDS)
                assertEquals(1, results.size)
            } finally {
                releaseUpdate.countDown()
                executor.shutdownNow()
                session.cancel()
                directory.deleteRecursively()
            }
        }
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

    @Test fun sessionResultsAreIdenticalWhenAsrOrDiarizationFinishesFirst() {
        val asrFirst = runSession(300_000, true)
        val inferenceFirst = runSession(300_000, false)
        assertEquals(asrFirst, inferenceFirst)
        assertEquals(listOf(0, 1, 2), asrFirst.map { it.windowIndex })
        assertEquals(listOf(false, false, true), asrFirst.map { it.isSessionFinal })
        assertEquals(30, asrFirst.sumOf { it.utterances.size })
    }

    @Test fun lateAsrCallbacksUseTheSameEvidenceAndKeepReturningSpeakerIdentity() {
        val speakers: (Int) -> FloatArray = { end ->
            if (end in 125001..242500) floatArrayOf(0f, 1f) else floatArrayOf(1f, 0f)
        }
        val immediate = runSession(360000, true, speakerForEnd = speakers)
        val delayed = runSession(360000, false, 15000, speakers)
        assertEquals(immediate, delayed)
        val utterances = immediate.flatMap { it.utterances }
        val a = utterances.first { it.beginTime == 1000 }.speakerIndex
        val b = utterances.first { it.beginTime == 161000 }.speakerIndex
        val returningA = utterances.first { it.beginTime == 281000 }.speakerIndex
        assertTrue(a >= 0)
        assertTrue(b >= 0)
        assertNotEquals(a, b)
        assertEquals(a, returningA)
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

    @Test fun fiveHoursOfAudioTimeDoesNotRetainPublishedTranscriptOrEmbeddings() {
        val results = runSession(5 * 60 * 60 * 1000, true)
        assertEquals(150, results.size)
        assertEquals(1, results.count { it.isSessionFinal })
        assertEquals(1800, results.sumOf { it.utterances.size })
    }

    private fun runSession(durationMs: Int, asrFirst: Boolean, asrDelayMs: Int = 0,
        speakerForEnd: (Int) -> FloatArray = { floatArrayOf(1f, 0f) }): List<SpeakerDiarizationResult> {
        mockConstruction(SpeakerDiarizationLocalClient::class.java).use {
            val results = mutableListOf<SpeakerDiarizationResult>()
            val frozen = mutableSetOf<String>()
            val observer = object : SpeakerDiarizationSessionObserver {
                override fun onUpdate(update: SpeakerDiarizationUpdate) {
                    assertFalse("update after publication: ${update.utteranceId}", update.utteranceId in frozen)
                }
                override fun onWindowResult(result: SpeakerDiarizationResult) { record(result) }
                override fun onFinished(result: SpeakerDiarizationResult) { record(result) }
                private fun record(result: SpeakerDiarizationResult) {
                    assertEquals(results.size, result.windowIndex)
                    result.utterances.forEach { assertTrue(frozen.add(it.utteranceId)) }
                    results += result.copy(inferenceMs = 0, rtf = 0f)
                }
            }
            val directory = Files.createTempDirectory("diarization-session-test").toFile()
            val session = SpeakerDiarizationSession(mock<Context>(), directory, 4, observer)
            val pendingAsr = java.util.ArrayDeque<Pair<Int, () -> Unit>>()
            val pcm = ByteArray(80_000)
            var firstSnapshot: SpeakerDiarizationResult? = null
            for (end in 2500..durationMs step 2500) {
                session.append(pcm)
                val final = if (end % 10_000 == 0) AsrResult("词", timestamps = listOf((end - 9000) / 1000f, (end - 1000) / 1000f)) else null
                if (final != null) ResultAudioTimeline.record(final, end * 16L)
                fun deliverAsr() {
                    if (final == null) return
                    session.observeAsrFinal(SpeechRecognitionResult(isFinal = true, result = "词", beginTime = end - 9000, endTime = end - 1000), final)
                    session.asrFinalDelivered(final)
                }
                if (asrDelayMs > 0 && final != null) pendingAsr.addLast(end + asrDelayMs to { deliverAsr() })
                if (asrDelayMs == 0 && asrFirst) deliverAsr()
                session.onWindow(window(end, speakerForEnd(end)))
                if (asrDelayMs == 0 && !asrFirst) deliverAsr()
                while (pendingAsr.isNotEmpty() && pendingAsr.first().first <= end) pendingAsr.removeFirst().second()
                if (results.isNotEmpty()) {
                    if (firstSnapshot == null) firstSnapshot = results.first().copy(utterances = results.first().utterances.toList(), speakerTurns = results.first().speakerTurns.toList())
                    assertEquals(firstSnapshot, results.first())
                }
                val observations = session.javaClass.getDeclaredField("recentObservations").apply { isAccessible = true }.get(session) as List<*>
                assertTrue("unbounded embedding history: ${observations.size}", observations.size <= 50 + asrDelayMs / 2500)
            }
            while (pendingAsr.isNotEmpty()) pendingAsr.removeFirst().second()
            session.finish()
            session.observeAsrFinal(SpeechRecognitionResult(isFinal = true, isLast = true), AsrResult("", isLast = true))
            session.onDrained()
            session.cancel()
            session.onWindow(window(durationMs + 2500))
            directory.deleteRecursively()
            return results
        }
    }

    private fun window(end: Int, embedding: FloatArray = floatArrayOf(1f, 0f)): DiarizationLocalWindowResult {
        val sampleEnd = end * 16L
        val realCount = minOf(sampleEnd, 160_000).toInt()
        val padding = 160_000 - realCount
        return DiarizationLocalWindowResult("w$end", maxOf(0, sampleEnd - 160_000), padding,
            sampleEnd, maxOf(0, sampleEnd - 40_000 - 24_000), maxOf(0, sampleEnd - 24_000), false,
            DiarizationWindowInferenceResult(
                listOf(SpeakerSegmentationSegment(padding, 160_000, 0, 1)),
                listOf(DiarizationEmbedding(0, minOf(realCount, 96_000), embedding,
                    if (realCount >= 40_000) embedding else null, speechRms = 0.1)), 1))
    }
}
