package com.amphion.dingqiao.diarization

import android.content.Context
import com.amphion.asr.AsrResult
import com.amphion.dingqiao.DiarizedUtterance
import com.amphion.dingqiao.SpeakerDiarizationDegradedReason
import com.amphion.dingqiao.SpeakerDiarizationResult
import com.amphion.dingqiao.SpeakerDiarizationUpdate
import com.amphion.dingqiao.SpeakerTurn
import com.amphion.dingqiao.SpeechRecognitionResult
import java.io.File
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.EOFException
import java.io.FileInputStream
import java.io.FileOutputStream
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

internal interface SpeakerDiarizationSessionObserver {
    fun onUpdate(update: SpeakerDiarizationUpdate)
    fun onFinished(result: SpeakerDiarizationResult)
}

internal interface SpeakerDiarizationController {
    fun append(audio: ByteArray)
    fun observeAsrFinal(payload: SpeechRecognitionResult, result: AsrResult): SpeechRecognitionResult
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
    private val client = SpeakerDiarizationLocalClient(context, workPath, this)
    private val registry = OnlineSpeakerRegistry(maxSpeakers, 0.72f, 0.05f)
    private val globalClusterer = SpeakerDiarizationGlobalClusterer(maxSpeakers, 0.72f)
    private val transcript = DiarizationTranscriptState()
    private val observationPath = File(client.checkpointDir(), "embedding-index.bin")
    private var recentObservations = mutableListOf<SpeakerEmbeddingObservation>()
    private var nextReclusterMs = RECLUSTER_INTERVAL_MS
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
                )
                decoratePayloadLocked(payload.copy(utteranceId = utteranceId))
            }
            value to finalizeIfReadyLocked()
        }
        dispatchFinal(finalDispatch)
        return decorated
    }

    @Synchronized
    override fun finish() {
        if (finishRequested || finished) return
        finishRequested = true
        client.finish()
    }

    @Synchronized
    override fun decoratePayload(payload: SpeechRecognitionResult): SpeechRecognitionResult {
        return decoratePayloadLocked(payload)
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
        client.cancel(onQuiescent)
    }

    @Synchronized
    fun cleanup(onQuiescent: (() -> Unit)? = null) = client.cleanup(onQuiescent)

    override fun onWindow(result: DiarizationLocalWindowResult) {
        val window = result
        val updates = synchronized(this) {
        if (finished) return
        inferenceMs += window.result.inferenceMs
        val channelIds = mutableMapOf<Int, String>()
        val channelConfidences = mutableMapOf<Int, Float>()
        val assignments = registry.assignBatch(
            window.result.embeddings.map { it.embedding },
            window.result.embeddings.map { it.speechSamples * 1000 / SAMPLE_RATE },
            (window.realEndSample * 1000 / SAMPLE_RATE).toInt(),
        )
        window.result.embeddings.forEachIndexed { index, embedding ->
            val assignment = assignments[index]
            channelIds[embedding.localSpeaker] = assignment.speakerId
            channelConfidences[embedding.localSpeaker] = assignment.confidence
            val observation = SpeakerEmbeddingObservation(
                embedding = embedding.embedding.copyOf(),
                durationMs = embedding.speechSamples * 1000 / SAMPLE_RATE,
                onlineSpeakerId = assignment.speakerId,
                endTimeMs = (window.realEndSample * 1000 / SAMPLE_RATE).toInt(),
                evidenceKey = "${window.jobId}:${embedding.localSpeaker}",
            )
            recentObservations += observation
            runCatching { appendObservation(observation) }.onFailure {
                onDegraded(
                    SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE,
                    "speaker diarization checkpoint failed: ${it.message ?: it.javaClass.simpleName}",
                )
            }
        }
        val turns = window.result.segments.mapNotNull { segment ->
            val localStart = max(0, segment.startSample - window.contentStartInWindowSample)
            val localEnd = max(localStart, segment.endSample - window.contentStartInWindowSample)
            val globalStart = max(window.commitStartSample, window.windowStartSample + localStart)
            val globalEnd = min(
                min(window.realEndSample, window.stableEndSample),
                window.windowStartSample + localEnd,
            )
            if (globalEnd <= globalStart) return@mapNotNull null
            val primary = channelIds[segment.speaker] ?: "UNKNOWN"
            val secondary = mutableListOf<String>()
            val secondaryEvidence = mutableListOf<String>()
            for (localSpeaker in 0 until LOCAL_SPEAKER_COUNT) {
                if (localSpeaker == segment.speaker ||
                    segment.speakerMask and (1 shl localSpeaker) == 0
                ) continue
                val id = channelIds[localSpeaker] ?: "UNKNOWN_SECONDARY"
                if (id != primary && id !in secondary) {
                    secondary += id
                    secondaryEvidence += "${window.jobId}:$localSpeaker"
                }
            }
            SpeakerTimelineTurn(
                beginTime = (globalStart * 1000 / SAMPLE_RATE).toInt(),
                endTime = (globalEnd * 1000 / SAMPLE_RATE).toInt(),
                speakerId = primary,
                secondarySpeakerIds = secondary,
                confidence = channelConfidences[segment.speaker] ?: 0f,
                overlap = segment.speakerMask and (segment.speakerMask - 1) != 0,
                evidenceKey = "${window.jobId}:${segment.speaker}",
                secondaryEvidenceKeys = secondaryEvidence,
            )
        }
        val published = transcript.applySpeakerTurns(turns).map { it.toPublic() }.toMutableList()
        published += reclusterRecentLocked((window.realEndSample * 1000 / SAMPLE_RATE).toInt())
        published
        }
        updates.forEach(observer::onUpdate)
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
        val observations = runCatching { loadObservations() }.getOrElse {
            onDegraded(
                SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE,
                "speaker diarization checkpoint read failed: ${it.message ?: it.javaClass.simpleName}",
            )
            recentObservations.toList()
        }
        val clustered = globalClusterer.cluster(observations)
        finalSpeakerCount = min(maxSpeakers, clustered.clusterCount)
        val updates = transcript.applyEvidenceRemap(
            evidenceRemap(observations, clustered.observationSpeakerIds),
        ).map { it.toPublic() }
        finished = true
        return FinalDispatch(updates, buildResultLocked(degradedReason, degradedMessage))
    }

    private fun reclusterRecentLocked(endTimeMs: Int): List<SpeakerDiarizationUpdate> {
        val fromTime = max(0, endTimeMs - RECENT_CORRECTION_MS)
        recentObservations = recentObservations.filterTo(mutableListOf()) { it.endTimeMs >= fromTime }
        if (endTimeMs < nextReclusterMs) return emptyList()
        nextReclusterMs = endTimeMs + RECLUSTER_INTERVAL_MS
        val clustered = globalClusterer.cluster(recentObservations)
        return transcript.applyEvidenceRemap(
            evidenceRemap(recentObservations, clustered.observationSpeakerIds),
            fromTime,
        ).map { it.toPublic() }
    }

    private fun dispatchFinal(dispatch: FinalDispatch?) {
        if (dispatch == null) return
        dispatch.updates.forEach(observer::onUpdate)
        observer.onFinished(dispatch.result)
    }

    private fun buildResultLocked(
        reason: SpeakerDiarizationDegradedReason,
        message: String?,
    ): SpeakerDiarizationResult {
        val utterances = transcript.finalUtterances().map {
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
            )
        }
        val turns = transcript.allTurns().map {
            SpeakerTurn(
                it.beginTime,
                it.endTime,
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
            speakerCount = if (finalSpeakerCount > 0) finalSpeakerCount else registry.speakerIds().size,
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

    private fun evidenceRemap(
        observations: List<SpeakerEmbeddingObservation>,
        speakerIds: List<String>,
    ): Map<String, String> = observations.indices.associate { index ->
        observations[index].evidenceKey to speakerIds.getOrElse(index) { "UNKNOWN" }
    }

    private fun appendObservation(observation: SpeakerEmbeddingObservation) {
        DataOutputStream(FileOutputStream(observationPath, true).buffered()).use { output ->
            output.writeInt(observation.durationMs)
            output.writeInt(observation.endTimeMs)
            output.writeUTF(observation.onlineSpeakerId)
            output.writeUTF(observation.evidenceKey)
            output.writeInt(observation.embedding.size)
            observation.embedding.forEach(output::writeFloat)
        }
    }

    private fun loadObservations(): List<SpeakerEmbeddingObservation> {
        if (!observationPath.isFile) return emptyList()
        val result = mutableListOf<SpeakerEmbeddingObservation>()
        DataInputStream(FileInputStream(observationPath).buffered()).use { input ->
            while (true) {
                try {
                    val durationMs = input.readInt()
                    val endTimeMs = input.readInt()
                    val onlineSpeakerId = input.readUTF()
                    val evidenceKey = input.readUTF()
                    val dimension = input.readInt()
                    check(dimension in 1..4096) { "invalid embedding dimension: $dimension" }
                    val embedding = FloatArray(dimension) { input.readFloat() }
                    result += SpeakerEmbeddingObservation(
                        embedding,
                        durationMs,
                        onlineSpeakerId,
                        endTimeMs,
                        evidenceKey,
                    )
                } catch (_: EOFException) {
                    break
                }
            }
        }
        return result
    }

    private companion object {
        const val SAMPLE_RATE = 16_000
        const val LOCAL_SPEAKER_COUNT = 3
        const val RECENT_CORRECTION_MS = 60_000
        const val RECLUSTER_INTERVAL_MS = 30_000
    }
}

/** Keeps ASR usable and publishes an explicit final degradation if local storage setup fails. */
internal class DegradedSpeakerDiarizationSession(
    private val maxSpeakers: Int,
    private val observer: SpeakerDiarizationSessionObserver,
    private val degradedReason: SpeakerDiarizationDegradedReason,
    private val degradedMessage: String,
) : SpeakerDiarizationController {
    private val transcript = DiarizationTranscriptState()
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
                )
                payload.copy(utteranceId = id)
            }
            value to finalizeIfReadyLocked()
        }
        finalResult?.let(observer::onFinished)
        return decorated
    }

    override fun finish() {
        val finalResult = synchronized(this) {
            if (finished) return
            finishRequested = true
            finalizeIfReadyLocked()
        }
        finalResult?.let(observer::onFinished)
    }

    override fun decoratePayload(payload: SpeechRecognitionResult): SpeechRecognitionResult = payload

    override fun bestResult(
        reason: SpeakerDiarizationDegradedReason,
        message: String?,
    ): SpeakerDiarizationResult = synchronized(this) {
        buildResult(if (reason == SpeakerDiarizationDegradedReason.NONE) degradedReason else reason, message ?: degradedMessage)
    }

    override fun cancel(onQuiescent: (() -> Unit)?) {
        synchronized(this) { finished = true }
        onQuiescent?.invoke()
    }

    private fun finalizeIfReadyLocked(): SpeakerDiarizationResult? {
        if (!finishRequested || !asrTailObserved || finished) return null
        finished = true
        return buildResult(degradedReason, degradedMessage)
    }

    private fun buildResult(
        reason: SpeakerDiarizationDegradedReason,
        message: String?,
    ) = SpeakerDiarizationResult(
        utterances = transcript.finalUtterances().map {
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
