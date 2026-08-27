package com.amphion.dingqiao.diarization

import com.k2fsa.sherpa.onnx.SpeakerEmbeddingExtractor
import com.k2fsa.sherpa.onnx.SpeakerEmbeddingExtractorConfig
import kotlin.math.min

internal data class DiarizationEmbedding(
    val localSpeaker: Int,
    val speechSamples: Int,
    val embedding: FloatArray,
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

    fun process(samples: FloatArray): DiarizationWindowInferenceResult {
        val started = System.nanoTime()
        val segments = segmenter.process(samples)
        val embeddings = (0 until LOCAL_SPEAKER_COUNT).mapNotNull { localSpeaker ->
            val channelSamples = collectSingleSpeakerSamples(samples, segments, localSpeaker)
            if (channelSamples.size < MIN_EMBEDDING_SAMPLES) return@mapNotNull null
            val stream = extractor.createStream()
            try {
                stream.acceptWaveform(channelSamples, SAMPLE_RATE)
                if (!extractor.isReady(stream)) return@mapNotNull null
                DiarizationEmbedding(localSpeaker, channelSamples.size, extractor.compute(stream))
            } finally {
                stream.release()
            }
        }
        return DiarizationWindowInferenceResult(
            segments,
            embeddings,
            (System.nanoTime() - started) / 1_000_000,
        )
    }

    override fun close() {
        runCatching { extractor.release() }
        runCatching { segmenter.close() }
    }

    private fun collectSingleSpeakerSamples(
        samples: FloatArray,
        segments: List<SpeakerSegmentationSegment>,
        localSpeaker: Int,
    ): FloatArray {
        val expectedMask = 1 shl localSpeaker
        val result = FloatArray(MAX_EMBEDDING_SAMPLES)
        var count = 0
        for (segment in segments) {
            if (segment.speakerMask != expectedMask || count >= result.size) continue
            val start = segment.startSample.coerceIn(0, samples.size)
            val end = segment.endSample.coerceIn(start, samples.size)
            val take = min(end - start, result.size - count)
            if (take <= 0) continue
            samples.copyInto(result, count, start, start + take)
            count += take
        }
        return result.copyOf(count)
    }

    private companion object {
        const val SAMPLE_RATE = 16_000
        const val LOCAL_SPEAKER_COUNT = 3
        const val MIN_EMBEDDING_SAMPLES = SAMPLE_RATE
        const val MAX_EMBEDDING_SAMPLES = SAMPLE_RATE * 5 / 2
    }
}
