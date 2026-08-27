package com.amphion.dingqiao.diarization

import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sqrt

internal data class DiarizationInferenceWindow(
    val startSample: Long,
    val endSample: Long,
    val realEndSample: Long,
    val commitStartSample: Long,
    val stableEndSample: Long,
    val finalWindow: Boolean,
)

internal class DiarizationWindowScheduler(
    sampleRate: Int,
    windowMs: Int = 10_000,
    hopMs: Int = 2_500,
    rightContextMs: Int = 1_500,
) {
    private val windowSamples = (sampleRate * windowMs / 1_000.0).roundToInt().toLong()
    private val hopSamples = (sampleRate * hopMs / 1_000.0).roundToInt().toLong()
    private val rightContextSamples = (sampleRate * rightContextMs / 1_000.0).roundToInt().toLong()
    private var totalSamples = 0L
    private var nextWindowEnd = hopSamples
    private var committedThroughSample = 0L
    private var finished = false

    init {
        require(sampleRate > 0 && windowMs > 0 && hopMs > 0 && rightContextMs >= 0)
    }

    fun acceptSamples(sampleCount: Int): List<DiarizationInferenceWindow> {
        check(!finished) { "Diarization window scheduler is already finished" }
        require(sampleCount >= 0)
        totalSamples += sampleCount
        val windows = mutableListOf<DiarizationInferenceWindow>()
        while (totalSamples >= nextWindowEnd) {
            val end = nextWindowEnd
            val stableEnd = max(end - rightContextSamples, 0)
            windows += DiarizationInferenceWindow(
                startSample = max(0, end - windowSamples),
                endSample = end,
                realEndSample = end,
                commitStartSample = committedThroughSample,
                stableEndSample = stableEnd,
                finalWindow = false,
            )
            committedThroughSample = stableEnd
            nextWindowEnd += hopSamples
        }
        return windows
    }

    fun finish(): DiarizationInferenceWindow {
        check(!finished) { "Diarization window scheduler is already finished" }
        finished = true
        val end = max(totalSamples, windowSamples)
        return DiarizationInferenceWindow(
            startSample = max(0, end - windowSamples),
            endSample = end,
            realEndSample = totalSamples,
            commitStartSample = committedThroughSample,
            stableEndSample = totalSamples,
            finalWindow = true,
        )
    }
}

internal data class SpeakerAssignment(
    val speakerId: String,
    val confidence: Float,
    val created: Boolean,
)

private data class MutableSpeakerEntry(
    val speakerId: String,
    var centroid: FloatArray,
    var speechDurationMs: Int,
    var lastSeenMs: Int,
)

internal class OnlineSpeakerRegistry(
    private val maxSpeakers: Int = 4,
    private val similarityThreshold: Float = 0.72f,
    private val topMargin: Float = 0.05f,
) {
    private val entries = mutableListOf<MutableSpeakerEntry>()

    init {
        require(maxSpeakers > 0)
    }

    fun assignBatch(
        rawEmbeddings: List<FloatArray?>,
        speechDurationsMs: List<Int>,
        atMs: Int,
    ): List<SpeakerAssignment> {
        require(rawEmbeddings.size == speechDurationsMs.size)
        val embeddings = rawEmbeddings.mapIndexed { index, value ->
            if (value == null || speechDurationsMs[index] < 1_000) null else normalize(value)
        }
        val entryBestObservation = IntArray(entries.size) { -1 }
        val entryBestScore = FloatArray(entries.size) { Float.NEGATIVE_INFINITY }
        val ranked = embeddings.mapIndexed { observation, embedding ->
            if (embedding == null) emptyList() else entries.indices.map { entryIndex ->
                val score = cosine(entries[entryIndex].centroid, embedding)
                if (score > entryBestScore[entryIndex]) {
                    entryBestScore[entryIndex] = score
                    entryBestObservation[entryIndex] = observation
                }
                entryIndex to score
            }.sortedByDescending { it.second }
        }
        val result = MutableList(embeddings.size) {
            SpeakerAssignment("UNKNOWN", 0f, false)
        }
        embeddings.forEachIndexed { observation, embedding ->
            if (embedding == null) return@forEachIndexed
            val best = ranked[observation].getOrNull(0)
            val second = ranked[observation].getOrNull(1)
            val mutual = best != null && entryBestObservation[best.first] == observation
            val unambiguous = mutual && best!!.second >= similarityThreshold &&
                (second == null || best.second - second.second >= topMargin)
            if (unambiguous) {
                val entry = entries[best!!.first]
                updateCentroid(entry, embedding, speechDurationsMs[observation], atMs)
                result[observation] = SpeakerAssignment(
                    entry.speakerId,
                    best.second.coerceIn(0f, 1f),
                    false,
                )
            } else if (entries.size < maxSpeakers) {
                val entry = MutableSpeakerEntry(
                    speakerId = "S${entries.size + 1}",
                    centroid = embedding,
                    speechDurationMs = speechDurationsMs[observation],
                    lastSeenMs = atMs,
                )
                entries += entry
                result[observation] = SpeakerAssignment(entry.speakerId, 1f, true)
            } else if (best != null) {
                result[observation] = SpeakerAssignment("UNKNOWN", best.second.coerceIn(0f, 1f), false)
            }
        }
        return result
    }

    fun speakerIds(): List<String> = entries.map { it.speakerId }

    private fun updateCentroid(entry: MutableSpeakerEntry, embedding: FloatArray, durationMs: Int, atMs: Int) {
        val total = entry.speechDurationMs + durationMs
        val mixed = FloatArray(embedding.size) { index ->
            (entry.centroid[index] * entry.speechDurationMs + embedding[index] * durationMs) / total
        }
        entry.centroid = normalize(mixed) ?: entry.centroid
        entry.speechDurationMs = total
        entry.lastSeenMs = atMs
    }
}

internal data class SpeakerEmbeddingObservation(
    val embedding: FloatArray,
    val durationMs: Int,
    val onlineSpeakerId: String,
    val endTimeMs: Int,
    val evidenceKey: String,
)

internal data class SpeakerClusterResult(
    val observationSpeakerIds: List<String>,
    val clusterCount: Int,
)

private data class MutableCluster(
    val indexes: MutableList<Int>,
    var centroid: FloatArray,
    var durationMs: Int,
)

internal class SpeakerDiarizationGlobalClusterer(
    private val maxSpeakers: Int = 4,
    private val similarityThreshold: Float = 0.72f,
) {
    fun cluster(observations: List<SpeakerEmbeddingObservation>): SpeakerClusterResult {
        val clusters = seedMicroClusters(observations)
        while (clusters.size > 1) {
            var bestLeft = -1
            var bestRight = -1
            var bestScore = -1f
            for (left in clusters.indices) {
                for (right in left + 1 until clusters.size) {
                    val score = cosine(clusters[left].centroid, clusters[right].centroid)
                    if (score > bestScore) {
                        bestScore = score
                        bestLeft = left
                        bestRight = right
                    }
                }
            }
            if (bestScore < similarityThreshold) break
            merge(clusters, bestLeft, bestRight)
        }
        val sorted = clusters.sortedByDescending { it.durationMs }
        val assignments = MutableList(observations.size) { "UNKNOWN" }
        val displayIds = matchDisplayIds(sorted, observations)
        sorted.forEachIndexed { clusterIndex, cluster ->
            cluster.indexes.forEach { assignments[it] = displayIds.getOrElse(clusterIndex) { "UNKNOWN" } }
        }
        return SpeakerClusterResult(assignments, clusters.size)
    }

    private fun seedMicroClusters(observations: List<SpeakerEmbeddingObservation>): MutableList<MutableCluster> {
        val clusters = mutableListOf<MutableCluster>()
        observations.forEachIndexed { index, observation ->
            val centroid = normalize(observation.embedding) ?: return@forEachIndexed
            val best = clusters.indices.maxByOrNull { cosine(clusters[it].centroid, centroid) }
            val bestScore = best?.let { cosine(clusters[it].centroid, centroid) } ?: -1f
            if (best != null && (bestScore >= 0.88f || clusters.size >= 96)) {
                val temporary = mutableListOf(
                    clusters[best],
                    MutableCluster(mutableListOf(index), centroid, observation.durationMs),
                )
                merge(temporary, 0, 1)
                clusters[best] = temporary[0]
            } else {
                clusters += MutableCluster(mutableListOf(index), centroid, observation.durationMs)
            }
        }
        return clusters
    }

    private fun merge(clusters: MutableList<MutableCluster>, leftIndex: Int, rightIndex: Int) {
        val left = clusters[leftIndex]
        val right = clusters[rightIndex]
        val duration = left.durationMs + right.durationMs
        val centroid = FloatArray(left.centroid.size) { index ->
            (left.centroid[index] * left.durationMs + right.centroid[index] * right.durationMs) /
                max(1, duration)
        }
        left.indexes += right.indexes
        left.centroid = normalize(centroid) ?: left.centroid
        left.durationMs = duration
        clusters.removeAt(rightIndex)
    }

    private fun matchDisplayIds(
        clusters: List<MutableCluster>,
        observations: List<SpeakerEmbeddingObservation>,
    ): List<String> {
        val assignable = min(maxSpeakers, clusters.size)
        var bestScore = Long.MIN_VALUE
        var best = emptyList<String>()
        fun search(clusterIndex: Int, remaining: List<String>, current: List<String>, score: Long) {
            if (clusterIndex >= assignable) {
                if (score > bestScore) {
                    bestScore = score
                    best = current
                }
                return
            }
            remaining.forEach { speakerId ->
                val duration = clusters[clusterIndex].indexes.sumOf { index ->
                    if (observations[index].onlineSpeakerId == speakerId) observations[index].durationMs.toLong() else 0L
                }
                search(clusterIndex + 1, remaining - speakerId, current + speakerId, score + duration)
            }
        }
        search(0, (1..maxSpeakers).map { "S$it" }, emptyList(), 0)
        return best + List(max(0, clusters.size - best.size)) { "UNKNOWN" }
    }
}

internal fun normalize(values: FloatArray): FloatArray? {
    if (values.isEmpty() || values.any { !it.isFinite() }) return null
    val squared = values.fold(0.0) { acc, value -> acc + value * value }
    if (squared <= 0.0) return null
    val norm = sqrt(squared).toFloat()
    return FloatArray(values.size) { values[it] / norm }
}

internal fun cosine(left: FloatArray, right: FloatArray): Float {
    if (left.size != right.size) return Float.NEGATIVE_INFINITY
    var score = 0f
    for (index in left.indices) score += left[index] * right[index]
    return score
}
