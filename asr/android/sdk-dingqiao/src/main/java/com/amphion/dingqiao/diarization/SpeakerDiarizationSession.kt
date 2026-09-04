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
        val observations = recentObservations.filter { it.endTimeMs <= evidenceEndTime && it.endTimeMs > beginTime }
            .map { it.copy(onlineSpeakerId = "UNKNOWN", anchorId = committedRegistry.matchKnown(it.embedding)) }
        val clustered = globalClusterer.cluster(observations)
        val remap = mutableMapOf<String, String>()
        for (cluster in clustered.clusters) {
            val anchor = cluster.indexes.mapNotNull { observations[it].anchorId }.firstOrNull()
            val id = if (anchor != null) {
                committedRegistry.commitKnown(anchor, cluster.centroid, cluster.durationMs, endTime)
                anchor
            } else {
                committedRegistry.assignBatch(listOf(cluster.centroid), listOf(cluster.durationMs), endTime)[0].speakerId
            }
            cluster.indexes.forEach { remap[observations[it].evidenceKey] = id }
        }
        transcript.applyEvidenceRemap(remap)
        finalSpeakerCount = committedRegistry.speakerIds().size
        registry = committedRegistry.fork()
        terminalPayload?.let { decoratedTerminalPayload = decoratePayloadLocked(it) }
        val result = buildResultLocked(degradedReason, degradedMessage, endTime, beginTime).copy(isSessionFinal = isSessionFinal)
        transcript.commitThrough(endTime)
        val needed = transcript.allTurns().flatMap { listOfNotNull(it.evidenceKey) + it.secondaryEvidenceKeys }.toSet()
        recentObservations.removeAll { it.endTimeMs <= endTime && it.evidenceKey !in needed }
        return result
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
        val utterances = transcript.finalUtterances(endTime).map {
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
        utterances = transcript.finalUtterances(endTime).map {
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
