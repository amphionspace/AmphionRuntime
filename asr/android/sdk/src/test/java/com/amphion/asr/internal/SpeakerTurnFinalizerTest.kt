package com.amphion.asr.internal

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class SpeakerTurnFinalizerTest {
    @Test
    fun `C1 diarization selects latest stable target to other boundary`() {
        val fixture = generateSequence(File(System.getProperty("user.dir"))) { it.parentFile }
            .map { root -> File(root, "asr/tools/testdata/speaker_turn/c1_sequential_diarization.json") }
            .firstOrNull { it.isFile }
            ?.readText()
            ?: error("cannot locate shared C1 diarization fixture from ${System.getProperty("user.dir")}")
        val sampleRate = fixture.number("sample_rate")
        val totalSamples = fixture.number("total_samples")
        val expectedCut = fixture.number("expected_cut_sample")
        val segments = fixture.segmentObjects().map { segment ->
            SpeakerTurnSegment(
                startSample = segment.number("start_sample"),
                endSample = segment.number("end_sample"),
                speaker = segment.number("speaker"),
            )
        }
        val scores = mapOf(0 to 0.667f, 1 to 0.017f)
        val finalizer = SpeakerTurnFinalizer(
            sampleRate = sampleRate,
            windowSamples = 24_000,
            hopSamples = 8_000,
            consecutiveBelow = 2,
            maximumSamples = totalSamples,
        )
        finalizer.accept(FloatArray(totalSamples) { 0.1f })
        finalizer.observeScore(96_000, 0.459f, 0.35f)
        finalizer.observeScore(104_000, 0.072f, 0.35f)
        finalizer.observeScore(112_000, -0.036f, 0.35f)

        val split = finalizer.resolveDiarized(segments, 0.35f) { _, speaker -> scores[speaker] }

        assertNotNull(split)
        assertEquals(expectedCut, split?.cutSample)
        assertEquals(expectedCut, split?.prefix?.size)
        assertEquals(totalSamples - expectedCut, split?.suffix?.size)
    }

    @Test
    fun `diarized boundary must agree with speaker score transition`() {
        val finalizer = SpeakerTurnFinalizer(16_000, 24_000, 8_000, 2, 64_000)
        finalizer.accept(FloatArray(64_000) { 0.1f })
        finalizer.observeScore(48_000, 0.363f, 0.35f)
        finalizer.observeScore(56_000, -0.038f, 0.35f)
        finalizer.observeScore(64_000, 0.031f, 0.35f)

        val split = finalizer.resolveDiarized(
            listOf(
                SpeakerTurnSegment(6_000, 20_000, 0),
                SpeakerTurnSegment(20_000, 52_000, 1),
                SpeakerTurnSegment(52_000, 64_000, 0),
            ),
            0.35f,
        ) { _, speaker -> if (speaker == 0) 0.526f else 0.088f }

        assertNull(split)
        assertEquals(
            "diarization-outside-score-transition:20000:not-in:24000-48000",
            finalizer.lastResolutionReason(),
        )
    }

    @Test
    fun sequentialTurnUsesQuietValleyAndReplaysSuffix() {
        val samples = sequentialSamples()
        val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        finalizer.accept(samples)

        assertEquals(SpeakerTurnScoreState.TARGET_CONFIRMED, finalizer.observeScore(2_000, 0.65f, 0.35f))
        assertEquals(SpeakerTurnScoreState.BELOW, finalizer.observeScore(3_000, 0.20f, 0.35f))
        assertEquals(SpeakerTurnScoreState.DEPARTURE, finalizer.observeScore(3_200, 0.10f, 0.35f))

        val split = finalizer.resolve(floatArrayOf(0.3f, 1.0f, 2.2f), 0.35f) { _, start, end ->
            when {
                end <= 2_200 -> 0.60f
                start >= 2_200 -> 0.10f
                else -> null
            }
        }
        assertNotNull(split)
        assertEquals(2_200, split!!.cutSample)
        assertEquals(2_200, split.prefix.size)
        assertEquals(1_400, split.suffix.size)
        assertEquals(samples[2_200], split.suffix[0])
    }

    @Test
    fun boundaryIsIndependentOfPublicPcmPartitioning() {
        val samples = sequentialSamples()

        fun cut(partitions: IntArray): Int? {
            val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
            var offset = 0
            for (size in partitions) {
                finalizer.accept(samples.copyOfRange(offset, offset + size))
                offset += size
            }
            finalizer.observeScore(2_000, 0.65f, 0.35f)
            finalizer.observeScore(3_000, 0.20f, 0.35f)
            finalizer.observeScore(3_200, 0.10f, 0.35f)
            return finalizer.resolve(floatArrayOf(0.3f, 1.0f, 2.2f), 0.35f) { _, start, end ->
                when {
                    end <= 2_200 -> 0.60f
                    start >= 2_200 -> 0.10f
                    else -> null
                }
            }?.cutSample
        }

        assertEquals(2_200, cut(intArrayOf(3_600)))
        assertEquals(2_200, cut(intArrayOf(137, 863, 41, 1_559, 1_000)))
    }

    @Test
    fun departureWaitsForBoundedRightContextBeforeCommitting() {
        val samples = FloatArray(4_200).also { buffer ->
            for (index in 0 until 2_500) buffer[index] = if (index % 2 == 0) 0.2f else -0.2f
            for (index in 2_600 until buffer.size) buffer[index] = if (index % 2 == 0) 0.15f else -0.15f
        }
        val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        samples.fill(0f, 2_500, 2_600)
        finalizer.accept(samples.copyOfRange(0, 3_700))
        finalizer.observeScore(2_500, 0.65f, 0.35f)
        finalizer.observeScore(3_500, 0.20f, 0.35f)
        finalizer.observeScore(3_700, 0.10f, 0.35f)

        val scorer = { _: FloatArray, start: Int, end: Int ->
            when {
                end <= 2_500 -> 0.60f
                start >= 2_500 -> 0.10f
                else -> null
            }
        }
        assertNull(finalizer.resolve(floatArrayOf(0.3f, 1.0f, 2.5f), 0.35f, scorer))
        assertEquals(true, finalizer.needsMoreContext())

        finalizer.accept(samples.copyOfRange(3_700, samples.size))
        val split = finalizer.resolve(floatArrayOf(0.3f, 1.0f, 2.5f), 0.35f, scorer)
        assertEquals(false, finalizer.needsMoreContext())
        assertEquals(2_500, split?.cutSample)
    }

    @Test
    fun acousticResolverScansTransitionInsteadOfTrustingOneLateValley() {
        val samples = FloatArray(5_000).apply {
            fill(0.2f, 0, 2_000)
            fill(0.12f, 2_000, size)
            fill(0f, 2_750, 2_900)
        }
        val finalizer = SpeakerTurnFinalizer(1_000, 1_000, 250, 2, 10_000)
        finalizer.accept(samples)
        finalizer.observeScore(2_500, 0.60f, 0.35f)
        finalizer.observeScore(3_000, 0.20f, 0.35f)
        finalizer.observeScore(3_250, 0.10f, 0.35f)

        var scoreCalls = 0
        val split = finalizer.resolve(floatArrayOf(), 0.35f) { _, start, end ->
            scoreCalls += 1
            when {
                end <= 2_000 -> 0.62f
                start >= 2_000 -> 0.08f
                else -> 0.20f
            }
        }

        assertNotNull(split)
        assertEquals(2_000, split?.cutSample)
        assertEquals(true, scoreCalls <= 4)
        assertEquals(true, finalizer.lastResolutionReason().contains("candidate=2000"))
    }

    @Test
    fun ambiguousOrNonSequentialBoundaryFailsOpen() {
        val continuous = FloatArray(3_600) { if (it % 2 == 0) 0.2f else -0.2f }

        val oneDip = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        oneDip.accept(continuous)
        oneDip.observeScore(2_000, 0.65f, 0.35f)
        assertEquals(SpeakerTurnScoreState.BELOW, oneDip.observeScore(2_400, 0.20f, 0.35f))
        assertNull(oneDip.resolve(floatArrayOf(0.3f, 1.0f, 2.2f), 0.35f) { _, _, _ -> 0.1f })

        val noValley = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        noValley.accept(continuous)
        noValley.observeScore(2_000, 0.65f, 0.35f)
        noValley.observeScore(3_000, 0.20f, 0.35f)
        noValley.observeScore(3_200, 0.10f, 0.35f)
        assertNull(noValley.resolve(floatArrayOf(0.3f, 1.0f, 2.2f), 0.35f) { _, _, _ -> 0.1f })

        val contradictory = SpeakerTurnFinalizer(1_000, 1_000, 200, 2, 10_000)
        val withValley = continuous.copyOf().apply { fill(0f, 2_000, 2_200) }
        contradictory.accept(withValley)
        contradictory.observeScore(2_000, 0.65f, 0.35f)
        contradictory.observeScore(3_000, 0.20f, 0.35f)
        contradictory.observeScore(3_200, 0.10f, 0.35f)
        assertNull(contradictory.resolve(floatArrayOf(0.3f, 1.0f, 2.2f), 0.35f) { _, _, _ -> 0.60f })
    }

    private fun sequentialSamples(): FloatArray = FloatArray(3_600).also { samples ->
        for (index in 0 until 2_000) samples[index] = if (index % 2 == 0) 0.2f else -0.2f
        for (index in 2_200 until samples.size) samples[index] = if (index % 2 == 0) 0.15f else -0.15f
    }
}

private fun String.number(name: String): Int =
    Regex("\\\"$name\\\"\\s*:\\s*(-?\\d+)").find(this)?.groupValues?.get(1)?.toInt()
        ?: error("missing integer field $name")

private fun String.segmentObjects(): List<String> {
    val body = Regex("\\\"segments\\\"\\s*:\\s*\\[(.*?)]", RegexOption.DOT_MATCHES_ALL)
        .find(this)?.groupValues?.get(1) ?: error("missing segments")
    return Regex("\\{(.*?)\\}", RegexOption.DOT_MATCHES_ALL)
        .findAll(body)
        .map { it.value }
        .toList()
}
