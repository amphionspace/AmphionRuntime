package com.amphion.dingqiao.diarization

import android.content.Context
import com.amphion.asr.AsrResult
import com.amphion.asr.internal.ResultAudioTimeline
import com.amphion.dingqiao.DiarizedUtterance
import com.amphion.dingqiao.SpeakerDiarizationDegradedReason
import com.amphion.dingqiao.SpeakerDiarizationResult
import com.amphion.dingqiao.SpeakerDiarizationUpdate
import com.amphion.dingqiao.SpeakerTurn
import com.amphion.dingqiao.SpeechRecognitionResult
import java.io.File
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

internal interface SpeakerDiarizationSessionObserver {
    fun onUpdate(update: SpeakerDiarizationUpdate)
    fun onWindowResult(result: SpeakerDiarizationResult) {}
    fun onFinished(result: SpeakerDiarizationResult)
}

internal interface SpeakerDiarizationController {
    fun append(audio: ByteArray)
    fun observeAsrFinal(payload: SpeechRecognitionResult, result: AsrResult): SpeechRecognitionResult
    fun asrFinalDelivered(result: AsrResult) {}
    fun finish()
    fun decoratePayload(payload: SpeechRecognitionResult): SpeechRecognitionResult
    fun bestResult(
        reason: SpeakerDiarizationDegradedReason,
        message: String?,
    ): SpeakerDiarizationResult
    fun cancel(onQuiescent: (() -> Unit)? = null)
}

internal class SpeakerDiarizationSession(
    context: Context,
    workPath: File,
    private val maxSpeakers: Int,
    private val observer: SpeakerDiarizationSessionObserver,
) : SpeakerDiarizationLocalObserver, SpeakerDiarizationController {
    // Recognize the first/known speaker as before; require more speech to add another.
    private val minAdditionalSpeakerSpeechMs = 3000
    private var speakerLevelReference = 0.0
    private val client = SpeakerDiarizationLocalClient(context, workPath, this)
    private var registry = OnlineSpeakerRegistry(maxSpeakers, 0.72f, 0.05f)
    private val globalClusterer = SpeakerDiarizationGlobalClusterer(maxSpeakers, 0.72f)
    private val transcript = DiarizationTranscriptState()
    private val commitClock = DiarizationCommitClock()
    private val committedRegistry = OnlineSpeakerRegistry(maxSpeakers, 0.72f, 0.05f)
    private val callbacks = DiarizationCallbackQueue()
    private var inferenceEndMs = 0
    private var windowIndex = 0
    private var terminalPayload: SpeechRecognitionResult? = null
    private var decoratedTerminalPayload: SpeechRecognitionResult? = null
    private var recentObservations = mutableListOf<SpeakerEmbeddingObservation>()
    private val recentTurnQueries = mutableListOf<SpeakerTurnQuery>()
    private data class PendingBoundaryRefinement(val value: DiarizationBoundaryRefinement, val evidenceEndTimeMs: Int)
    private val recentRefinements = mutableListOf<PendingBoundaryRefinement>()
    private val publishedSpeakerIds = mutableSetOf<String>()
    private var totalSamples = 0L
    private var lastAsrEndMs = 0
    private var inferenceMs = 0L
    private var degradedReason = SpeakerDiarizationDegradedReason.NONE
    private var degradedMessage: String? = null
    private var finishRequested = false
    private var processDrained = false
    private var asrTailObserved = false
    private var finished = false
    private var finalSpeakerCount = 0

    private data class FinalDispatch(
        val updates: List<SpeakerDiarizationUpdate>,
        val result: SpeakerDiarizationResult,
    )

    private data class SpeakerTurnQuery(
        val evidenceKey: String,
        val contextEvidenceKey: String,
        val embedding: FloatArray,
        val endTimeMs: Int,
        val complementaryEmbedding: FloatArray? = null,
        val localQueries: List<DiarizationLocalIdentityQuery> = emptyList(),
    )

    init { require(maxSpeakers in 1..4) }

    @Synchronized
    override fun append(audio: ByteArray) {
        if (finishRequested || finished) return
        totalSamples += audio.size / 2
        client.append(audio)
    }

    override fun observeAsrFinal(
        payload: SpeechRecognitionResult,
        result: AsrResult,
    ): SpeechRecognitionResult {
        val (decorated, finalDispatch) = synchronized(this) {
            if (payload.isLast) asrTailObserved = true
            val value = if (payload.result.isEmpty()) {
                payload
            } else {
                val timestampsMs = result.timestamps.map { (it * 1000).roundToInt() }
                val beginTime = payload.beginTime ?: timestampsMs.firstOrNull() ?: lastAsrEndMs
                val endTime = payload.endTime ?: timestampsMs.lastOrNull()
                    ?: (totalSamples * 1000 / SAMPLE_RATE).toInt()
                lastAsrEndMs = max(lastAsrEndMs, endTime)
                val utteranceId = transcript.addUtterance(
                    rawText = result.rawText,
                    text = payload.result,
                    tokens = result.tokens,
                    tokenTimesMs = timestampsMs,
                    beginTime = beginTime,
                    endTime = endTime,
                    audioEndTime = ((ResultAudioTimeline.endSample(result) ?: totalSamples) * 1000 / SAMPLE_RATE).toInt(),
                )
                decoratePayloadLocked(payload.copy(utteranceId = utteranceId))
            }
            if (payload.isLast) terminalPayload = value
            value to finalizeIfReadyLocked()
        }
        dispatchFinal(finalDispatch)
        return decorated
    }

    override fun asrFinalDelivered(result: AsrResult) {
        synchronized(this) {
            if (finished || result.isLast) return
            val endSample = ResultAudioTimeline.endSample(result) ?: return
            commitClock.observeEndpoint((endSample * 1000 / SAMPLE_RATE).toInt())
            flushReadyWindowsLocked()
        }
        dispatchWindows()
    }

    @Synchronized
    override fun finish() {
        if (finishRequested || finished) return
        finishRequested = true
        client.finish()
    }

    @Synchronized
    override fun decoratePayload(payload: SpeechRecognitionResult): SpeechRecognitionResult {
        return if (payload.isLast) decoratedTerminalPayload ?: decoratePayloadLocked(payload) else decoratePayloadLocked(payload)
    }

    private fun decoratePayloadLocked(payload: SpeechRecognitionResult): SpeechRecognitionResult {
        val utteranceId = payload.utteranceId ?: return payload
        val assignment = transcript.currentAssignment(utteranceId) ?: return payload
        return payload.copy(
            speakerIndex = speakerIndexFromInternalId(assignment.speakerId, maxSpeakers),
            secondarySpeakerIndexes = speakerIndexesFromInternalIds(
                assignment.secondarySpeakerIds,
                maxSpeakers,
                true,
            ),
            speakerConfidence = assignment.confidence,
        )
    }

    @Synchronized
    override fun bestResult(
        reason: SpeakerDiarizationDegradedReason,
        message: String?,
    ): SpeakerDiarizationResult = buildResultLocked(reason, message)

    @Synchronized
    override fun cancel(onQuiescent: (() -> Unit)?) {
        finished = true
        callbacks.close()
        client.cancel(onQuiescent)
    }

    @Synchronized
    fun cleanup(onQuiescent: (() -> Unit)? = null) = client.cleanup(onQuiescent)

    override fun onWindow(result: DiarizationLocalWindowResult) {
        val window = result
        synchronized(this) {
        if (finished) return
        inferenceMs += window.result.inferenceMs
        inferenceEndMs = (window.realEndSample * 1000 / SAMPLE_RATE).toInt()
        window.result.refinements.forEach { recentRefinements += PendingBoundaryRefinement(it, inferenceEndMs) }
        val channelIds = mutableMapOf<Int, String>()
        val channelConfidences = mutableMapOf<Int, Float>()
        val ownedStart = window.commitStartSample - window.windowStartSample + window.contentStartInWindowSample
        val ownedEnd = min(window.realEndSample, window.stableEndSample) -
            window.windowStartSample + window.contentStartInWindowSample
        // Only current output channels compete for online identities. Retain all
        // contextual embeddings below for window-final clustering.
        // Prioritize principal voices within 6 dB of the observed speech level.
        // Quieter speech stays UNKNOWN and cannot occupy a role slot.
        window.result.embeddings.forEach { speakerLevelReference = maxOf(speakerLevelReference, it.speechRms) }
        val activeEmbeddings = window.result.embeddings.filter { embedding ->
            embedding.speechRms > 0 && embedding.speechRms >= speakerLevelReference * 0.5 &&
            window.result.segments.any { segment ->
                segment.speakerMask and (1 shl embedding.localSpeaker) != 0 &&
                    max(ownedStart, segment.startSample.toLong()) < min(ownedEnd, segment.endSample.toLong())
            }
        }
        val assignments = registry.assignBatch(
            activeEmbeddings.map { it.embedding },
            activeEmbeddings.map { it.speechSamples * 1000 / SAMPLE_RATE },
            (window.realEndSample * 1000 / SAMPLE_RATE).toInt(),
            activeEmbeddings.map { it.speechSamples * 1000 / SAMPLE_RATE >= minAdditionalSpeakerSpeechMs },
        )
        window.result.embeddings.forEach { embedding ->
            val assignment = assignments.getOrNull(activeEmbeddings.indexOf(embedding))
            if (assignment != null) {
                channelIds[embedding.localSpeaker] = assignment.speakerId
                channelConfidences[embedding.localSpeaker] = assignment.confidence
            }
            val observation = SpeakerEmbeddingObservation(
                embedding = embedding.embedding.copyOf(),
                speechRms = embedding.speechRms,
                levelEligibleAtObservation = embedding.speechRms > 0 && embedding.speechRms >= speakerLevelReference * 0.5,
                durationMs = embedding.speechSamples * 1000 / SAMPLE_RATE,
                onlineSpeakerId = assignment?.speakerId ?: "UNKNOWN",
                endTimeMs = (window.realEndSample * 1000 / SAMPLE_RATE).toInt(),
                evidenceKey = "${window.jobId}:${embedding.localSpeaker}",
                queryEmbedding = embedding.queryEmbedding?.copyOf(),
                complementaryEmbedding = embedding.complementaryEmbedding?.copyOf(),
            )
            recentObservations += observation
        }
        val turns = window.result.segments.mapIndexedNotNull { segmentIndex, segment ->
            val localStart = max(0, segment.startSample - window.contentStartInWindowSample)
            val localEnd = max(localStart, segment.endSample - window.contentStartInWindowSample)
            val globalStart = max(window.commitStartSample, window.windowStartSample + localStart)
            val globalEnd = min(
                min(window.realEndSample, window.stableEndSample),
                window.windowStartSample + localEnd,
            )
            if (globalEnd <= globalStart) return@mapIndexedNotNull null
            val contextEvidenceKey = "${window.jobId}:${segment.speaker}"
            val evidenceKey = if (segment.queryEmbedding == null) contextEvidenceKey else {
                val key = "$contextEvidenceKey:t$segmentIndex"
                recentTurnQueries += SpeakerTurnQuery(key, contextEvidenceKey,
                    segment.queryEmbedding.copyOf(), (window.realEndSample * 1000 / SAMPLE_RATE).toInt(),
                    segment.complementaryEmbedding?.copyOf(), segment.localQueries)
                key
            }
            val primary = channelIds[segment.speaker] ?: "UNKNOWN"
            val secondary = mutableListOf<String>()
            val secondaryEvidence = mutableListOf<String>()
            for (localSpeaker in 0 until LOCAL_SPEAKER_COUNT) {
                if (localSpeaker == segment.speaker ||
                    segment.speakerMask and (1 shl localSpeaker) == 0
                ) continue
                val id = channelIds[localSpeaker] ?: "UNKNOWN_SECONDARY"
                secondary += id
                secondaryEvidence += "${window.jobId}:$localSpeaker"
            }
            SpeakerTimelineTurn(
                beginTime = (globalStart * 1000 / SAMPLE_RATE).toInt(),
                endTime = (globalEnd * 1000 / SAMPLE_RATE).toInt(),
                speakerId = primary,
                secondarySpeakerIds = secondary,
                confidence = channelConfidences[segment.speaker] ?: 0f,
                overlap = segment.speakerMask and (segment.speakerMask - 1) != 0,
                evidenceKey = evidenceKey,
                secondaryEvidenceKeys = secondaryEvidence,
            )
        }
        val published = transcript.applySpeakerTurns(turns).map { it.toPublic() }.toMutableList()
        published.forEach { update -> callbacks.enqueue { observer.onUpdate(update) } }
        flushReadyWindowsLocked()
        }
        dispatchWindows()
    }

    override fun onDrained() {
        val finalDispatch = synchronized(this) {
            if (!finishRequested || finished) return
            processDrained = true
            finalizeIfReadyLocked()
        }
        dispatchFinal(finalDispatch)
    }

    override fun onDegraded(reason: SpeakerDiarizationDegradedReason, message: String) {
        synchronized(this) {
            if (degradedReason != SpeakerDiarizationDegradedReason.NONE) return
            degradedReason = reason
            degradedMessage = message
        }
    }

    private fun finalizeIfReadyLocked(): FinalDispatch? {
        if (!finishRequested || finished || !processDrained || !asrTailObserved) return null
        flushReadyWindowsLocked()
        val result = commitWindowLocked((totalSamples * 1000 / SAMPLE_RATE).toInt(), Int.MAX_VALUE, true)
        finished = true
        callbacks.enqueue { observer.onFinished(result) }
        return FinalDispatch(emptyList(), result)
    }

    private fun flushReadyWindowsLocked() {
        if (finished) return
        val progress = if (degradedReason == SpeakerDiarizationDegradedReason.NONE) inferenceEndMs else Int.MAX_VALUE
        while (true) {
            val boundary = commitClock.takeReady(progress) ?: break
            val result = commitWindowLocked(boundary.endTime, boundary.evidenceEndTime, false, boundary.beginTime)
            if (result.utterances.isNotEmpty() || result.speakerTurns.isNotEmpty()) {
                windowIndex += 1
                callbacks.enqueue { observer.onWindowResult(result) }
            }
        }
    }

    private fun commitWindowLocked(endTime: Int, evidenceEndTime: Int, isSessionFinal: Boolean,
        beginTime: Int = commitClock.beginTime()): SpeakerDiarizationResult {
        val windowObservations = recentObservations.filter { it.endTimeMs <= evidenceEndTime && it.endTimeMs > beginTime }
        val observations = windowObservations.filter {
            it.speechRms > 0 && it.speechRms >= speakerLevelReference * 0.5 }
            .map { it.copy(onlineSpeakerId = "UNKNOWN", anchorId = committedRegistry.matchKnown(it.embedding)) }
        val clustered = globalClusterer.cluster(observations)
        // Quiet evidence can corroborate identity without enrolling or labeling quiet speech.
        val identitySupport = windowObservations.mapNotNull { observation ->
            observation.queryEmbedding?.let { SpeakerIdentitySupport(observation.embedding, it) }
        }
        val turnQueries = recentTurnQueries.filter { it.endTimeMs <= evidenceEndTime && it.endTimeMs > beginTime }
        val clusters = clustered.clusters.toMutableList()
        if (committedRegistry.speakerIds().isEmpty()) {
            // Repeated short context cannot outweigh a better-supported first identity.
            val firstSupported = clusters.indexOfFirst { cluster ->
                cluster.indexes.any { observations[it].durationMs >= minAdditionalSpeakerSpeechMs }
            }
            val firstOwnedIndex = observations.indexOfFirst { it.queryEmbedding != null }
            // Retain an initial voice that also leads coherent evidence; later
            // repeated short contexts must not take the first-role exemption.
            val leadingOwnsFirst = firstOwnedIndex >= 0 &&
                clusters.firstOrNull()?.indexes?.contains(firstOwnedIndex) == true
            if (firstSupported > 0 && !leadingOwnsFirst) clusters.add(0, clusters.removeAt(firstSupported))
        }
        val remap = mutableMapOf<String, String>()
        // Clear ineligible evidence instead of retaining an earlier provisional ID.
        windowObservations.forEach { observation ->
            remap[observation.evidenceKey] = "UNKNOWN"
        }
        for (cluster in clusters) {
            val anchor = cluster.indexes.mapNotNull { observations[it].anchorId }.firstOrNull()
            // A mixed member cannot assign the entire cluster to an old person.
            val id = if (anchor != null && committedRegistry.matchQuery(cluster.centroid,
                    committedRegistry.speakerIds().toSet())?.speakerId == anchor) {
                committedRegistry.commitKnown(anchor, cluster.centroid, cluster.durationMs, endTime)
                anchor
            } else {
                // Repeated overlapping context is not additional independent PCM.
                // Context can mix earlier speakers. A new role must also have
                // evidence from an owned output slice before becoming a query target.
                val canEnroll = cluster.indexes.any { observations[it].durationMs >= minAdditionalSpeakerSpeechMs } &&
                    cluster.indexes.any { observations[it].queryEmbedding != null }
                val assignment = committedRegistry.assignBatch(listOf(cluster.centroid), listOf(cluster.durationMs),
                    endTime, listOf(canEnroll),
                    listOf(cluster.indexes.mapNotNull { observations[it].queryEmbedding }), identitySupport)[0]
                if (assignment.created) committedRegistry.bindComplementaryProfile(assignment.speakerId,
                    cluster.indexes.map { observations[it].complementaryEmbedding },
                    cluster.indexes.map { observations[it].durationMs })
                assignment.speakerId
            }
            cluster.indexes.forEach { remap[observations[it].evidenceKey] = id }
        }
        // Preserve independently admitted new voices when a later loud person
        // raises the reference. Existing profiles cannot change through this path.
        val recoveredNovelKeys = mutableSetOf<String>()
        val firstReference = observations.firstOrNull {
            it.queryEmbedding != null && remap[it.evidenceKey] != "UNKNOWN"
        }
        val referenceEstablishedAt = if (publishedSpeakerIds.isNotEmpty()) beginTime
            else firstReference?.endTimeMs ?: Int.MAX_VALUE
        val historicalEligible = windowObservations.filter {
            it.levelEligibleAtObservation && it.endTimeMs >= referenceEstablishedAt &&
                it.speechRms < speakerLevelReference * 0.5
        }
        if (historicalEligible.isNotEmpty() && committedRegistry.speakerIds().size < maxSpeakers) {
            val historicalClusters = globalClusterer.cluster(historicalEligible)
            for (cluster in historicalClusters.clusters) {
                val members = cluster.indexes.map { historicalEligible[it] }
                val queries = members.mapNotNull { it.queryEmbedding }
                if (members.none { it.durationMs >= minAdditionalSpeakerSpeechMs } || queries.isEmpty()) continue
                val preview = committedRegistry.fork().assignBatch(listOf(cluster.centroid),
                    listOf(cluster.durationMs), endTime, listOf(true), listOf(queries), identitySupport)[0]
                if (!preview.created) continue
                val assignment = committedRegistry.assignBatch(listOf(cluster.centroid),
                    listOf(cluster.durationMs), endTime, listOf(true), listOf(queries), identitySupport)[0]
                if (!assignment.created) continue
                committedRegistry.bindComplementaryProfile(assignment.speakerId,
                    members.map { it.complementaryEmbedding }, members.map { it.durationMs })
                members.forEach {
                    remap[it.evidenceKey] = assignment.speakerId
                    recoveredNovelKeys += it.evidenceKey
                }
            }
        }
        turnQueries.forEach { remap[it.evidenceKey] = remap[it.contextEvidenceKey] ?: "UNKNOWN" }
        val established = publishedSpeakerIds.toMutableSet()
        collectOutputSpeakerIds(beginTime, endTime, remap, established)
        val queryConfidences = mutableMapOf<String, Float>()
        for (observation in observations) {
            val query = observation.queryEmbedding ?: continue
            val match = committedRegistry.matchQuery(query, established) ?: continue
            if (match.speakerId != remap[observation.evidenceKey]) {
                remap[observation.evidenceKey] = match.speakerId
                queryConfidences[observation.evidenceKey] = match.confidence
            }
        }
        val eligibleKeys = observations.map { it.evidenceKey }.toSet() + recoveredNovelKeys
        for (query in turnQueries) {
            remap[query.evidenceKey] = remap[query.contextEvidenceKey] ?: "UNKNOWN"
            queryConfidences[query.contextEvidenceKey]?.let { queryConfidences[query.evidenceKey] = it }
            if (query.contextEvidenceKey !in eligibleKeys) {
                val context = windowObservations.find { it.evidenceKey == query.contextEvidenceKey }
                val match = context?.let { committedRegistry.matchQuietQuery(query.embedding, it.embedding, established) }
                if (match != null) {
                    remap[query.evidenceKey] = match.speakerId
                    queryConfidences[query.evidenceKey] = match.confidence
                }
                continue
            }
            val match = committedRegistry.matchQuery(query.embedding, established) ?: continue
            remap[query.evidenceKey] = match.speakerId
            queryConfidences[query.evidenceKey] = match.confidence
        }
        for (query in turnQueries) {
            if (remap[query.evidenceKey] != "UNKNOWN" || query.contextEvidenceKey !in eligibleKeys) continue
            val secondaryQuery = query.complementaryEmbedding ?: continue
            val context = windowObservations.find { it.evidenceKey == query.contextEvidenceKey } ?: continue
            val secondaryContext = context.complementaryEmbedding ?: continue
            val match = committedRegistry.matchComplementaryQuery(query.embedding, context.embedding,
                secondaryQuery, secondaryContext, established) ?: continue
            remap[query.evidenceKey] = match.speakerId
            queryConfidences[query.evidenceKey] = match.confidence
        }
        // The long quiet context only proposes a known identity. Local PCM must
        // independently confirm every newly named output slice.
        for (query in turnQueries) {
            if (remap[query.evidenceKey] != "UNKNOWN" || query.contextEvidenceKey in eligibleKeys ||
                query.complementaryEmbedding == null || query.localQueries.isEmpty()) continue
            val context = windowObservations.find { it.evidenceKey == query.contextEvidenceKey } ?: continue
            val complementaryContext = context.complementaryEmbedding ?: continue
            val proposed = committedRegistry.matchComplementaryQuery(query.embedding, context.embedding,
                query.complementaryEmbedding, complementaryContext, established) ?: continue
            for (local in query.localQueries) {
                val match = committedRegistry.matchLocalQuery(local.embedding, local.complementaryEmbedding, established) ?: continue
                if (match.speakerId != proposed.speakerId) continue
                val from = maxOf(beginTime, (local.startSample * 1000.0 / SAMPLE_RATE).roundToInt())
                val through = minOf(endTime, (local.endSample * 1000.0 / SAMPLE_RATE).roundToInt())
                transcript.resolveUnknownSpan(query.evidenceKey, from, through, match.speakerId, match.confidence, remap)
            }
        }
        for ((refinement, evidenceThrough) in recentRefinements) {
            val start = (refinement.startSample * 1000.0 / SAMPLE_RATE).roundToInt()
            val cut = (refinement.cutSample * 1000.0 / SAMPLE_RATE).roundToInt()
            val end = (refinement.endSample * 1000.0 / SAMPLE_RATE).roundToInt()
            if (start < beginTime || end > endTime || evidenceThrough > evidenceEndTime) continue
            val left = committedRegistry.matchComplementaryQuery(refinement.leftEmbedding, refinement.leftEmbedding,
                refinement.leftComplementaryEmbedding, refinement.leftComplementaryEmbedding, established) ?: continue
            val right = committedRegistry.matchComplementaryQuery(refinement.rightEmbedding, refinement.rightEmbedding,
                refinement.rightComplementaryEmbedding, refinement.rightComplementaryEmbedding, established) ?: continue
            if (left.speakerId == right.speakerId) continue
            transcript.refineSingleSpeakerSpan(start, cut, end, left.speakerId, right.speakerId,
                left.confidence, right.confidence, remap)
        }
        transcript.applyEvidenceRemap(remap, 0, queryConfidences)
        finalSpeakerCount = committedRegistry.speakerIds().size
        registry = committedRegistry.fork()
        terminalPayload?.let { decoratedTerminalPayload = decoratePayloadLocked(it) }
        val result = buildResultLocked(degradedReason, degradedMessage, endTime, beginTime).copy(isSessionFinal = isSessionFinal)
        collectOutputSpeakerIds(beginTime, endTime, emptyMap(), publishedSpeakerIds)
        transcript.commitThrough(endTime)
        recentRefinements.removeAll { it.value.startSample * 1000.0 / SAMPLE_RATE < endTime }
        val needed = transcript.allTurns().flatMap { listOfNotNull(it.evidenceKey) + it.secondaryEvidenceKeys }.toMutableSet()
        recentTurnQueries.removeAll { it.endTimeMs <= endTime && it.evidenceKey !in needed }
        recentTurnQueries.forEach { needed += it.contextEvidenceKey }
        recentObservations.removeAll { it.endTimeMs <= endTime && it.evidenceKey !in needed }
        return result
    }

    private fun collectOutputSpeakerIds(beginTime: Int, endTime: Int,
        remap: Map<String, String>, ids: MutableSet<String>) {
        for (turn in transcript.allTurns()) {
            if (turn.beginTime >= endTime || turn.endTime <= beginTime) continue
            val primary = remap[turn.evidenceKey] ?: turn.speakerId
            if (primary.startsWith("S")) ids += primary
            turn.secondaryEvidenceSpeakerIds.forEachIndexed { index, id ->
                val secondary = remap[turn.secondaryEvidenceKeys.getOrNull(index)] ?: id
                if (secondary.startsWith("S")) ids += secondary
            }
        }
    }

    private fun dispatchWindows() { callbacks.drain() }

    private fun dispatchFinal(dispatch: FinalDispatch?) {
        if (dispatch != null) callbacks.drain()
    }

    private fun buildResultLocked(
        reason: SpeakerDiarizationDegradedReason,
        message: String?,
        endTime: Int = (totalSamples * 1000 / SAMPLE_RATE).toInt(),
        beginTime: Int = commitClock.beginTime(),
    ): SpeakerDiarizationResult {
        val utterances = transcript.sentenceUtterances(endTime).map {
            DiarizedUtterance(
                it.utteranceId,
                it.rawText,
                it.text,
                it.beginTime,
                it.endTime,
                speakerIndexFromInternalId(it.speakerId, maxSpeakers),
                speakerIndexesFromInternalIds(it.secondarySpeakerIds, maxSpeakers, true),
                it.confidence,
                it.overlap,
                it.sourceUtteranceId,
                it.speakerInferred,
            )
        }
        val turns = transcript.allTurns().filter { it.endTime > beginTime && it.beginTime < endTime }.map {
            SpeakerTurn(
                maxOf(beginTime, it.beginTime),
                minOf(endTime, it.endTime),
                speakerIndexFromInternalId(it.speakerId, maxSpeakers),
                speakerIndexesFromInternalIds(it.secondarySpeakerIds, maxSpeakers, true),
                it.confidence,
                it.overlap || it.secondarySpeakerIds.isNotEmpty(),
            )
        }
        val audioMs = max(1L, totalSamples * 1000 / SAMPLE_RATE)
        return SpeakerDiarizationResult(
            utterances = utterances,
            speakerTurns = turns,
            speakerCount = finalSpeakerCount,
            windowIndex = windowIndex,
            windowBeginTime = beginTime,
            windowEndTime = endTime,
            degraded = reason != SpeakerDiarizationDegradedReason.NONE,
            degradedReason = reason,
            degradedMessage = message,
            inferenceMs = inferenceMs,
            rtf = inferenceMs.toFloat() / audioMs,
        )
    }

    private fun DiarizationTranscriptUpdate.toPublic() = SpeakerDiarizationUpdate(
        utteranceId,
        revision,
        speakerIndexFromInternalId(speakerId, maxSpeakers),
        speakerIndexesFromInternalIds(secondarySpeakerIds, maxSpeakers, true),
        beginTime,
        endTime,
        confidence,
    )

    private companion object { const val SAMPLE_RATE = 16_000; const val LOCAL_SPEAKER_COUNT = 3 }
}

internal class DegradedSpeakerDiarizationSession(
    private val maxSpeakers: Int,
    private val observer: SpeakerDiarizationSessionObserver,
    private val degradedReason: SpeakerDiarizationDegradedReason,
    private val degradedMessage: String,
) : SpeakerDiarizationController {
    private val callbacks = DiarizationCallbackQueue()
    private val transcript = DiarizationTranscriptState()
    private val commitClock = DiarizationCommitClock()
    private var windowIndex = 0
    private var totalSamples = 0L
    private var lastAsrEndMs = 0
    private var finishRequested = false
    private var asrTailObserved = false
    private var finished = false

    override fun append(audio: ByteArray) {
        synchronized(this) {
            if (!finishRequested && !finished) totalSamples += audio.size / 2
        }
    }

    override fun observeAsrFinal(
        payload: SpeechRecognitionResult,
        result: AsrResult,
    ): SpeechRecognitionResult {
        val (decorated, finalResult) = synchronized(this) {
            if (payload.isLast) asrTailObserved = true
            val value = if (payload.result.isEmpty()) payload else {
                val timestampsMs = result.timestamps.map { (it * 1000).roundToInt() }
                val beginTime = payload.beginTime ?: timestampsMs.firstOrNull() ?: lastAsrEndMs
                val endTime = payload.endTime ?: timestampsMs.lastOrNull()
                    ?: (totalSamples * 1000 / SAMPLE_RATE).toInt()
                lastAsrEndMs = max(lastAsrEndMs, endTime)
                val id = transcript.addUtterance(
                    result.rawText,
                    payload.result,
                    result.tokens,
                    timestampsMs,
                    beginTime,
                    endTime,
                    ((ResultAudioTimeline.endSample(result) ?: totalSamples) * 1000 / SAMPLE_RATE).toInt(),
                )
                payload.copy(utteranceId = id)
            }
            value to finalizeIfReadyLocked()
        }
        if (finalResult != null) callbacks.drain()
        return decorated
    }

    override fun asrFinalDelivered(result: AsrResult) {
        synchronized(this) {
            if (finished || result.isLast) return
            val endSample = ResultAudioTimeline.endSample(result) ?: return
            commitClock.observeEndpoint((endSample * 1000 / SAMPLE_RATE).toInt())
            while (true) {
                val boundary = commitClock.takeReady(Int.MAX_VALUE) ?: break
                val value = buildResult(degradedReason, degradedMessage, boundary.endTime, boundary.beginTime)
                transcript.commitThrough(boundary.endTime)
                if (value.utterances.isNotEmpty()) {
                    callbacks.enqueue { observer.onWindowResult(value) }; windowIndex++
                }
            }
        }
        callbacks.drain()
    }

    override fun finish() {
        val finalResult = synchronized(this) {
            if (finished) return
            finishRequested = true
            finalizeIfReadyLocked()
        }
        if (finalResult != null) callbacks.drain()
    }

    override fun decoratePayload(payload: SpeechRecognitionResult): SpeechRecognitionResult = payload

    override fun bestResult(
        reason: SpeakerDiarizationDegradedReason,
        message: String?,
    ): SpeakerDiarizationResult = synchronized(this) {
        buildResult(if (reason == SpeakerDiarizationDegradedReason.NONE) degradedReason else reason, message ?: degradedMessage)
    }

    override fun cancel(onQuiescent: (() -> Unit)?) {
        synchronized(this) { finished = true; callbacks.close() }
        onQuiescent?.invoke()
    }

    private fun finalizeIfReadyLocked(): SpeakerDiarizationResult? {
        if (!finishRequested || !asrTailObserved || finished) return null
        finished = true
        val result = buildResult(degradedReason, degradedMessage).copy(isSessionFinal = true)
        callbacks.enqueue { observer.onFinished(result) }
        return result
    }

    private fun buildResult(
        reason: SpeakerDiarizationDegradedReason,
        message: String?,
        endTime: Int = (totalSamples * 1000 / SAMPLE_RATE).toInt(),
        beginTime: Int = commitClock.beginTime(),
    ) = SpeakerDiarizationResult(
        windowIndex = windowIndex, windowBeginTime = beginTime, windowEndTime = endTime,
        utterances = transcript.sentenceUtterances(endTime).map {
            DiarizedUtterance(
                it.utteranceId,
                it.rawText,
                it.text,
                it.beginTime,
                it.endTime,
                -1,
                emptyList(),
                0f,
                false,
            )
        },
        degraded = true,
        degradedReason = reason,
        degradedMessage = message,
    )

    private companion object {
        const val SAMPLE_RATE = 16_000
    }
}
