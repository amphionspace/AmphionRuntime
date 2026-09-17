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
)

internal data class DiarizationWindowInferenceResult(
    val segments: List<SpeakerSegmentationSegment>,
    val embeddings: List<DiarizationEmbedding>,
    val inferenceMs: Long,
)

/** Session-owned, fully offline inference using the same two models as HarmonyOS. */
internal class SpeakerDiarizationInference(
    segmentationModelPath: String,
    embeddingModelPath: String,
) : AutoCloseable {
    private val segmenter = SpeakerTurnSegmenter(segmentationModelPath)
    private val extractor = SpeakerEmbeddingExtractor(
        config = SpeakerEmbeddingExtractorConfig(
            model = embeddingModelPath,
            numThreads = 1,
            debug = false,
        ),
    )

    fun process(samples: FloatArray, queryStartSample: Int = 0, queryEndSample: Int = 0): DiarizationWindowInferenceResult {
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
                kotlin.math.sqrt(squaredLevel / channelSamples.size))
        }
        return DiarizationWindowInferenceResult(
            segments.map { segment ->
                if (segment.speakerMask != (1 shl segment.speaker) ||
                    maxOf(segment.startSample, queryStartSample) >= minOf(segment.endSample, queryEndSample)) {
                    segment
                } else {
                    // Separate runs on one channel must not share a mixed query.
                    val end = minOf(segment.endSample, segment.startSample + MAX_EMBEDDING_SAMPLES)
                    segment.copy(queryEmbedding = computeEmbedding(samples.copyOfRange(segment.startSample, end)))
                }
            },
            embeddings,
            (System.nanoTime() - started) / 1_000_000,
        )
    }

    override fun close() {
        runCatching { extractor.release() }
        runCatching { segmenter.close() }
    }

    private fun computeEmbedding(samples: FloatArray): FloatArray? {
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
