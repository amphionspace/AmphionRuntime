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

internal data class SpeakerIdentitySupport(val embedding: FloatArray, val queryEmbedding: FloatArray)

private data class SupportedIdentityMatch(val assignment: SpeakerAssignment, val retainAlternative: Boolean)

private data class MutableSpeakerEntry(
    val speakerId: String,
    var centroid: FloatArray,
    var speechDurationMs: Int,
    var lastSeenMs: Int,
    var alternateCentroid: FloatArray? = null,
    var complementaryCentroid: FloatArray? = null,
    var complementaryReferences: List<FloatArray> = emptyList(),
)

internal class OnlineSpeakerRegistry(
    private val maxSpeakers: Int = 4,
    private val similarityThreshold: Float = 0.72f,
    private val topMargin: Float = 0.05f,
) {
    private companion object { const val QUERY_SIMILARITY_THRESHOLD = 0.59f }
    private val entries = mutableListOf<MutableSpeakerEntry>()

    init {
        require(maxSpeakers > 0)
    }

    fun assignBatch(
        rawEmbeddings: List<FloatArray?>,
        speechDurationsMs: List<Int>,
        atMs: Int,
        allowAdditionalSpeaker: List<Boolean>? = null,
        enrollmentQueries: List<List<FloatArray>>? = null,
        identitySupport: List<SpeakerIdentitySupport> = emptyList(),
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
            } else if (entries.size < maxSpeakers && (entries.isEmpty() || (allowAdditionalSpeaker?.get(observation) ?: true)) &&
                (best == null || !mutual ||
                best.second < minOf(similarityThreshold, QUERY_SIMILARITY_THRESHOLD) ||
                confirmsNovelty(embedding, enrollmentQueries?.getOrNull(observation)))) {
                // Only intercept a new identity; preserve ordinary UNKNOWN decisions.
                val supported = matchSupportedIdentity(embedding, identitySupport,
                    enrollmentQueries?.getOrNull(observation).orEmpty())
                if (supported != null) {
                    if (supported.retainAlternative) entries.first {
                        it.speakerId == supported.assignment.speakerId
                    }.alternateCentroid = embedding.copyOf()
                    result[observation] = supported.assignment
                    return@forEachIndexed
                }
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

    private fun matchSupportedIdentity(embedding: FloatArray, support: List<SpeakerIdentitySupport>,
        ownedQueries: List<FloatArray>): SupportedIdentityMatch? {
        if (ownedQueries.isEmpty()) return null
        val sum = FloatArray(embedding.size)
        for (raw in ownedQueries) {
            val query = normalize(raw) ?: return null
            if (query.size != sum.size) return null
            for (i in sum.indices) sum[i] += query[i]
        }
        val owned = normalize(sum) ?: return null
        val alternativeMatch = matchExisting(embedding, QUERY_SIMILARITY_THRESHOLD, includeAlternate = true)
        val alternative = entries.find { it.speakerId == alternativeMatch?.speakerId }?.alternateCentroid
        if (alternativeMatch != null && alternative != null &&
            cosine(embedding, alternative) >= QUERY_SIMILARITY_THRESHOLD &&
            cosine(owned, alternative) >= QUERY_SIMILARITY_THRESHOLD) {
            // Reuse the fixed reference without recursively extending it.
            return SupportedIdentityMatch(alternativeMatch, false)
        }
        val scores = entries.map { cosine(it.centroid, embedding) }.toMutableList()
        val supportedScores = FloatArray(entries.size) { Float.NEGATIVE_INFINITY }
        for (item in support) {
            val context = normalize(item.embedding) ?: continue
            val query = normalize(item.queryEmbedding) ?: continue
            if (cosine(context, query) < similarityThreshold ||
                maxOf(cosine(owned, context), cosine(owned, query)) < QUERY_SIMILARITY_THRESHOLD) continue
            // Primary centroids only: alternative references cannot qualify support.
            val contextMatch = matchExisting(context, QUERY_SIMILARITY_THRESHOLD) ?: continue
            val queryMatch = matchExisting(query, QUERY_SIMILARITY_THRESHOLD) ?: continue
            if (contextMatch.speakerId != queryMatch.speakerId) continue
            val index = entries.indexOfFirst { it.speakerId == contextMatch.speakerId }
            supportedScores[index] = maxOf(supportedScores[index], cosine(embedding, query))
            scores[index] = maxOf(scores[index], supportedScores[index])
        }
        val ranked = entries.indices.sortedByDescending { scores[it] }
        val best = ranked.firstOrNull() ?: return null
        if (supportedScores[best] < QUERY_SIMILARITY_THRESHOLD ||
            (ranked.size > 1 && scores[best] - scores[ranked[1]] < topMargin)) return null
        return SupportedIdentityMatch(SpeakerAssignment(entries[best].speakerId,
            scores[best].coerceIn(0f, 1f), false), true)
    }

    private fun confirmsNovelty(embedding: FloatArray, queries: List<FloatArray>?): Boolean {
        if (queries == null || queries.size < 2) return false
        // Independent owned slices can prove novelty despite mixed context.
        val sum = FloatArray(embedding.size)
        for (query in queries) {
            val normalized = normalize(query) ?: return false
            if (normalized.size != sum.size) return false
            for (i in sum.indices) sum[i] += normalized[i]
        }
        val consensus = normalize(sum) ?: return false
        return cosine(consensus, embedding) >= similarityThreshold && entries.all {
            cosine(consensus, it.centroid) < minOf(similarityThreshold, QUERY_SIMILARITY_THRESHOLD)
        }
    }

    fun fork(): OnlineSpeakerRegistry = OnlineSpeakerRegistry(maxSpeakers, similarityThreshold, topMargin).also { copy ->
        entries.forEach { copy.entries += it.copy(centroid = it.centroid.copyOf(),
            alternateCentroid = it.alternateCentroid?.copyOf(), complementaryCentroid = it.complementaryCentroid?.copyOf(),
            complementaryReferences = it.complementaryReferences.map { reference -> reference.copyOf() }) }
    }

    fun matchKnown(raw: FloatArray): String? {
        return matchExisting(raw, similarityThreshold)?.speakerId
    }

    /** Query matching never enrolls roles or uses a context-only profile. */
    fun matchQuery(raw: FloatArray, establishedIds: Set<String>): SpeakerAssignment? {
        // Independent AISHELL3 calibration: maximum impostor cosine .5392 + .05 margin.
        return matchExisting(raw, QUERY_SIMILARITY_THRESHOLD, establishedIds)
            ?: matchExisting(raw, QUERY_SIMILARITY_THRESHOLD, establishedIds, true)
    }

    /** Quiet output needs strong agreement with an independently established alternative. */
    fun matchQuietQuery(raw: FloatArray, context: FloatArray, establishedIds: Set<String>): SpeakerAssignment? {
        val contextMatch = matchExisting(context, similarityThreshold, establishedIds, true) ?: return null
        val queryMatch = matchExisting(raw, similarityThreshold, establishedIds, true) ?: return null
        if (contextMatch.speakerId != queryMatch.speakerId) return null
        val alternative = entries.find { it.speakerId == queryMatch.speakerId }?.alternateCentroid ?: return null
        val embedding = normalize(raw) ?: return null
        val contextEmbedding = normalize(context) ?: return null
        val confidence = minOf(minOf(cosine(embedding, alternative), cosine(contextEmbedding, alternative)),
            minOf(contextMatch.confidence, queryMatch.confidence))
        if (confidence < similarityThreshold) return null
        return SpeakerAssignment(queryMatch.speakerId, confidence, false)
    }

    fun bindComplementaryProfile(id: String, embeddings: List<FloatArray?>, durations: List<Int>) {
        val entry = entries.find { it.speakerId == id } ?: return
        if (entry.complementaryCentroid != null || embeddings.isEmpty() || embeddings.size != durations.size) return
        val sum = FloatArray(embeddings.first()?.size ?: return)
        val references = mutableListOf<FloatArray>()
        embeddings.forEachIndexed { index, raw ->
            val value = raw?.let { normalize(it) } ?: return
            if (value.size != sum.size || durations[index] <= 0) return
            for (j in sum.indices) sum[j] += value[j] * durations[index]
            if (references.size < 8) references += value
        }
        entry.complementaryCentroid = normalize(sum)
        if (entry.complementaryCentroid != null) entry.complementaryReferences = references
    }

    fun matchComplementaryQuery(query: FloatArray, context: FloatArray, complementaryQuery: FloatArray,
        complementaryContext: FloatArray, establishedIds: Set<String>): SpeakerAssignment? {
        val primaryQuery = matchExisting(query, -1f, establishedIds) ?: return null
        val primaryContext = matchExisting(context, -1f, establishedIds) ?: return null
        if (primaryQuery.speakerId != primaryContext.speakerId) return null
        val secondaryQuery = matchExisting(complementaryQuery, 0.64f, establishedIds, false, true)
        val secondaryContext = matchExisting(complementaryContext, 0.64f, establishedIds, false, true)
        if (secondaryQuery?.speakerId == primaryQuery.speakerId && secondaryContext?.speakerId == primaryQuery.speakerId) {
            return SpeakerAssignment(primaryQuery.speakerId, minOf(secondaryQuery.confidence, secondaryContext.confidence), false)
        }
        // Fixed original enrollment references use a separately calibrated,
        // higher threshold; context and query must agree on the same reference.
        val normalizedQuery = normalize(complementaryQuery) ?: return null
        val normalizedContext = normalize(complementaryContext) ?: return null
        val ranked = entries.filter { it.speakerId in establishedIds }.map { entry ->
            entry.speakerId to (entry.complementaryReferences.maxOfOrNull { reference ->
                minOf(cosine(normalizedQuery, reference), cosine(normalizedContext, reference))
            } ?: Float.NEGATIVE_INFINITY)
        }.sortedByDescending { it.second }
        val best = ranked.firstOrNull() ?: return null
        val second = ranked.getOrNull(1)
        if (best.first != primaryQuery.speakerId || best.second < 0.68f ||
            (second != null && best.second - second.second < topMargin)) return null
        return SpeakerAssignment(primaryQuery.speakerId, minOf(1f, best.second), false)
    }

    fun matchLocalQuery(query: FloatArray, complementaryQuery: FloatArray, establishedIds: Set<String>): SpeakerAssignment? {
        val primary = matchExisting(query, .59f, establishedIds) ?: return null
        val complementary = matchExisting(complementaryQuery, .64f, establishedIds, useComplementary = true) ?: return null
        if (complementary.speakerId != primary.speakerId) return null
        return SpeakerAssignment(primary.speakerId, minOf(primary.confidence, complementary.confidence), false)
    }

    private fun matchExisting(raw: FloatArray, threshold: Float, allowedIds: Set<String>? = null,
        includeAlternate: Boolean = false, useComplementary: Boolean = false): SpeakerAssignment? {
        val embedding = normalize(raw) ?: return null
        val ranked = entries.filter { allowedIds == null || it.speakerId in allowedIds }
            .filter { !useComplementary || it.complementaryCentroid != null }
            .map { entry -> entry.speakerId to if (useComplementary) cosine(entry.complementaryCentroid!!, embedding)
                else maxOf(cosine(entry.centroid, embedding),
                if (includeAlternate) entry.alternateCentroid?.let { cosine(it, embedding) }
                    ?: Float.NEGATIVE_INFINITY else Float.NEGATIVE_INFINITY)
            }.sortedByDescending { it.second }
        val best = ranked.firstOrNull() ?: return null
        return if (best.second >= threshold &&
            (ranked.size < 2 || best.second - ranked[1].second >= topMargin))
            SpeakerAssignment(best.first, best.second.coerceIn(0f, 1f), false) else null
    }

    fun commitKnown(id: String, embedding: FloatArray, durationMs: Int, atMs: Int) {
        val entry = entries.find { it.speakerId == id } ?: return
        val normalized = normalize(embedding) ?: return
        updateCentroid(entry, normalized, durationMs, atMs)
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
    val anchorId: String? = null,
    val queryEmbedding: FloatArray? = null,
    val speechRms: Double = 0.0,
    val complementaryEmbedding: FloatArray? = null,
    val levelEligibleAtObservation: Boolean = false,
)

internal data class SpeakerClusterResult(
    val observationSpeakerIds: List<String>,
    val clusterCount: Int,
    val clusters: List<MutableCluster>,
)

internal data class MutableCluster(
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
                    if (!compatible(clusters[left].indexes, clusters[right].indexes, observations)) continue
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
        return SpeakerClusterResult(assignments, clusters.size, sorted)
    }

    private fun compatible(left: List<Int>, right: List<Int>, observations: List<SpeakerEmbeddingObservation>): Boolean =
        (left + right).mapNotNull { observations[it].anchorId }.distinct().size <= 1

    private fun seedMicroClusters(observations: List<SpeakerEmbeddingObservation>): MutableList<MutableCluster> {
        val clusters = mutableListOf<MutableCluster>()
        observations.forEachIndexed { index, observation ->
            val centroid = normalize(observation.embedding) ?: return@forEachIndexed
            val best = clusters.indices.filter { compatible(clusters[it].indexes, listOf(index), observations) }.maxByOrNull { cosine(clusters[it].centroid, centroid) }
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
