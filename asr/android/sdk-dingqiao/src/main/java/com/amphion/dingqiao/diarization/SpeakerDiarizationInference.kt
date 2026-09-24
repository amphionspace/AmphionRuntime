package com.amphion.dingqiao.diarization

import com.k2fsa.sherpa.onnx.SpeakerEmbeddingExtractor
import com.k2fsa.sherpa.onnx.SpeakerEmbeddingExtractorConfig
import kotlin.math.min

internal data class DiarizationEmbedding(
    val localSpeaker: Int,
    val speechSamples: Int,
    val embedding: FloatArray,
    val queryEmbedding: FloatArray? = null,
    val speechRms: Double = 0.0,
    val complementaryEmbedding: FloatArray? = null,
    val scoringEmbedding: FloatArray? = null,
)

internal data class DiarizationWindowInferenceResult(
    val segments: List<SpeakerSegmentationSegment>,
    val embeddings: List<DiarizationEmbedding>,
    val inferenceMs: Long,
    val refinements: List<DiarizationBoundaryRefinement> = emptyList(),
)

internal data class DiarizationBoundaryRefinement(
    val startSample: Long, val cutSample: Long, val endSample: Long,
    val leftEmbedding: FloatArray, val leftComplementaryEmbedding: FloatArray,
    val rightEmbedding: FloatArray, val rightComplementaryEmbedding: FloatArray,
)

internal data class DiarizationLocalIdentityQuery(
    val startSample: Long, val endSample: Long,
    val embedding: FloatArray, val complementaryEmbedding: FloatArray,
)

/** Session-owned, fully offline inference using the same models as HarmonyOS. */
internal class SpeakerDiarizationInference(
    segmentationModelPath: String,
    embeddingModelPath: String,
    private val communityPlda: Community1Plda? = null,
    complementaryModelPath: String? = null,
) : AutoCloseable {
    private data class SingleSpeakerRun(val startSample: Long, val endSample: Long)
    private val recentSingleSpeakerRuns = mutableListOf<SingleSpeakerRun>()
    private var speakerLevelReference = 0.0
    private val segmenter = SpeakerTurnSegmenter(segmentationModelPath)
    private val extractor = SpeakerEmbeddingExtractor(
        config = SpeakerEmbeddingExtractorConfig(
            model = embeddingModelPath,
            numThreads = 1,
            debug = false,
        ),
    )
    private val complementaryExtractor = complementaryModelPath?.let {
        try {
            SpeakerEmbeddingExtractor(config = SpeakerEmbeddingExtractorConfig(
                model = it, numThreads = 1, debug = false,
            ))
        } catch (t: Throwable) {
            runCatching { extractor.release() }
            runCatching { segmenter.close() }
            throw t
        }
    }

    fun process(samples: FloatArray, queryStartSample: Int = 0, queryEndSample: Int = 0,
        windowOriginSample: Long = 0): DiarizationWindowInferenceResult {
        val started = System.nanoTime()
        val segments = segmenter.process(samples)
        val embeddings = (0 until LOCAL_SPEAKER_COUNT).mapNotNull { localSpeaker ->
            val channelSamples = collectSingleSpeakerSamples(samples, segments, localSpeaker)
            val embedding = computeEmbedding(channelSamples) ?: return@mapNotNull null
            val querySamples = collectQuerySamples(samples, segments, localSpeaker,
                queryStartSample, queryEndSample)
            var squaredLevel = 0.0
            for (sample in channelSamples) squaredLevel += sample.toDouble() * sample
            DiarizationEmbedding(localSpeaker, channelSamples.size, embedding, computeEmbedding(querySamples),
                kotlin.math.sqrt(squaredLevel / channelSamples.size),
                complementaryExtractor?.let { computeEmbedding(channelSamples, it) },
                communityPlda?.project(embedding))
        }
        embeddings.forEach { speakerLevelReference = maxOf(speakerLevelReference, it.speechRms) }
        val queriedSegments = segments.map { segment ->
                if (segment.speakerMask != (1 shl segment.speaker) ||
                    maxOf(segment.startSample, queryStartSample) >= minOf(segment.endSample, queryEndSample)) {
                    segment
                } else {
                    // Separate runs on one channel must not share a mixed query.
                    val end = minOf(segment.endSample, segment.startSample + MAX_EMBEDDING_SAMPLES)
                    val runSamples = samples.copyOfRange(segment.startSample, end)
                    val query = computeEmbedding(runSamples)
                    val complementary = complementaryExtractor?.let { computeEmbedding(runSamples, it) }
                    val context = embeddings.find { it.localSpeaker == segment.speaker }
                    val local = if (context != null && context.speechRms > 0 && context.speechRms < speakerLevelReference * .5 &&
                        query != null && complementary != null)
                        queryQuietLocalIdentity(samples, segment, queryStartSample, queryEndSample, windowOriginSample)
                    else emptyList()
                    segment.copy(queryEmbedding = query, complementaryEmbedding = complementary, localQueries = local)
                }
            }
        val refinements = refineEarlierRuns(samples, segments, queryStartSample, windowOriginSample)
        return DiarizationWindowInferenceResult(queriedSegments, embeddings,
            (System.nanoTime() - started) / 1_000_000, refinements)
    }

    private fun queryQuietLocalIdentity(samples: FloatArray, segment: SpeakerSegmentationSegment,
        queryStartSample: Int, queryEndSample: Int, origin: Long): List<DiarizationLocalIdentityQuery> {
        val queries = mutableListOf<DiarizationLocalIdentityQuery>()
        val start = origin + maxOf(segment.startSample, queryStartSample)
        val end = origin + minOf(segment.endSample, queryEndSample)
        // Absolute 250-ms cells, each verified with 1.3 seconds of real local PCM.
        var cell = Math.floorDiv(start, 4000L)
        while (cell * 4000 < end) {
            val center = cell * 4000 + 2000
            val from = center - 10400
            val through = center + 10400
            if (from >= maxOf(0, origin) && through <= origin + samples.size) {
                val pcm = samples.copyOfRange((from - origin).toInt(), (through - origin).toInt())
                val primary = computeEmbedding(pcm)
                val complementary = complementaryExtractor?.let { computeEmbedding(pcm, it) }
                if (primary != null && complementary != null)
                    queries += DiarizationLocalIdentityQuery(maxOf(start, cell * 4000), minOf(end, (cell + 1) * 4000), primary, complementary)
            }
            cell++
        }
        return queries
    }

    private fun refineEarlierRuns(samples: FloatArray, segments: List<SpeakerSegmentationSegment>,
        queryStartSample: Int, origin: Long): List<DiarizationBoundaryRefinement> {
        val refinements = mutableListOf<DiarizationBoundaryRefinement>()
        for (index in 1 until segments.size) {
            val left = segments[index - 1]
            val right = segments[index]
            val cut = origin + right.startSample
            if (left.endSample != right.startSample || left.speaker == right.speaker ||
                left.speakerMask != (1 shl left.speaker) || right.speakerMask != (1 shl right.speaker) ||
                right.startSample >= queryStartSample || right.endSample - right.startSample < MIN_EMBEDDING_SAMPLES) continue
            val start = recentSingleSpeakerRuns.filter { it.startSample >= maxOf(0, origin) &&
                it.startSample < cut && it.endSample > cut && cut - it.startSample >= MIN_EMBEDDING_SAMPLES }
                .minOfOrNull { it.startSample } ?: continue
            val leftSamples = samples.copyOfRange(maxOf((start - origin).toInt(), right.startSample - MAX_EMBEDDING_SAMPLES), right.startSample)
            val rightSamples = samples.copyOfRange(right.startSample, minOf(right.endSample, right.startSample + MAX_EMBEDDING_SAMPLES))
            val leftEmbedding = computeEmbedding(leftSamples) ?: continue
            val leftComplementary = complementaryExtractor?.let { computeEmbedding(leftSamples, it) } ?: continue
            val rightEmbedding = computeEmbedding(rightSamples) ?: continue
            val rightComplementary = complementaryExtractor?.let { computeEmbedding(rightSamples, it) } ?: continue
            refinements += DiarizationBoundaryRefinement(start, cut, origin + minOf(right.endSample, queryStartSample),
                leftEmbedding, leftComplementary, rightEmbedding, rightComplementary)
        }
        recentSingleSpeakerRuns.removeAll { it.endSample <= origin }
        segments.filter { it.speakerMask == (1 shl it.speaker) }.forEach {
            recentSingleSpeakerRuns += SingleSpeakerRun(origin + it.startSample, origin + it.endSample)
        }
        return refinements
    }

    override fun close() {
        runCatching { extractor.release() }
        runCatching { complementaryExtractor?.release() }
        runCatching { segmenter.close() }
    }

    private fun computeEmbedding(samples: FloatArray, extractor: SpeakerEmbeddingExtractor = this.extractor): FloatArray? {
        if (samples.size < MIN_EMBEDDING_SAMPLES) return null
        val stream = extractor.createStream()
        try {
            stream.acceptWaveform(samples, SAMPLE_RATE)
            return if (extractor.isReady(stream)) extractor.compute(stream) else null
        } finally {
            stream.release()
        }
    }

    private fun collectSingleSpeakerSamples(
        samples: FloatArray,
        segments: List<SpeakerSegmentationSegment>,
        localSpeaker: Int,
        fromSample: Int = 0,
        throughSample: Int = samples.size,
    ): FloatArray {
        val expectedMask = 1 shl localSpeaker
        val result = FloatArray(MAX_EMBEDDING_SAMPLES)
        var count = 0
        for (segment in segments) {
            if (segment.speakerMask != expectedMask || count >= result.size) continue
            val start = maxOf(fromSample, segment.startSample).coerceIn(0, samples.size)
            val end = minOf(throughSample, segment.endSample).coerceIn(start, samples.size)
            val take = min(end - start, result.size - count)
            if (take <= 0) continue
            samples.copyInto(result, count, start, start + take)
            count += take
        }
        return result.copyOf(count)
    }

    private fun collectQuerySamples(
        samples: FloatArray,
        segments: List<SpeakerSegmentationSegment>,
        localSpeaker: Int,
        fromSample: Int,
        throughSample: Int,
    ): FloatArray {
        val start = fromSample.coerceIn(0, samples.size)
        val end = throughSample.coerceIn(start, samples.size)
        val masks = ByteArray(end - start)
        for (segment in segments) {
            val from = maxOf(start, segment.startSample)
            val through = minOf(end, segment.endSample)
            if (through > from) masks.fill(segment.speakerMask.toByte(), from - start, through - start)
        }
        val expectedMask = 1 shl localSpeaker
        var confirmedSpeech = 0
        var total = 0
        for (mask in masks) {
            if (mask.toInt() == expectedMask) confirmedSpeech++
            if (mask.toInt() == 0 || mask.toInt() == expectedMask) total++
        }
        if (confirmedSpeech < MIN_EMBEDDING_SAMPLES) return floatArrayOf()
        // Retain real unclassified PCM inside the output slice to avoid clipping
        // weak phonetic tails. Exclude other speakers and overlap; unclassified
        // samples do not count toward speech eligibility or enter enrollment.
        val result = FloatArray(min(total, MAX_EMBEDDING_SAMPLES))
        var offset = 0
        for (i in masks.indices) {
            if (offset >= result.size) break
            if (masks[i].toInt() == 0 || masks[i].toInt() == expectedMask) result[offset++] = samples[start + i]
        }
        return result
    }

    private companion object {
        const val SAMPLE_RATE = 16_000
        const val LOCAL_SPEAKER_COUNT = 3
        const val MIN_EMBEDDING_SAMPLES = SAMPLE_RATE
        // Retain later clean speech while bounding variable-length model workspace.
        const val MAX_EMBEDDING_SAMPLES = SAMPLE_RATE * 6
    }
}
