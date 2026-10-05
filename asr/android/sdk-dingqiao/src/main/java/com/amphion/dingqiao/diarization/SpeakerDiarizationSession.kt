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
    fun asrAudioProcessed(endSample: Long) {}
    fun finish(confirmedInitialSilence: Boolean = false)
    fun decoratePayload(payload: SpeechRecognitionResult): SpeechRecognitionResult
    fun bestResult(
        reason: SpeakerDiarizationDegradedReason,
        message: String?,
    ): SpeakerDiarizationResult
    /** Finish timeout: freeze speakers for audio already inferred instead of discarding them. */
    fun salvage() {}
    fun cancel(onQuiescent: (() -> Unit)? = null)
}

internal class SpeakerDiarizationSession(
    context: Context,
    workPath: File,
    private val maxSpeakers: Int,
    private val observer: SpeakerDiarizationSessionObserver,
) : SpeakerDiarizationLocalObserver, SpeakerDiarizationController {
    // Internal opt-in white-box observer. No capture or allocation in ordinary sessions.
    @Volatile internal var diagnostic: ((String, Map<String, Any?>) -> Unit)? = null
    private var diagnosticProcessedMs = 0
    private fun recordDecision(event: String, fields: Map<String, Any?>) {
        runCatching { diagnostic?.invoke(event, fields) }
    }
    private val client = SpeakerDiarizationLocalClient(context, workPath, this)
    private val transcript = DiarizationTranscriptState()
    private val commitClock = DiarizationCommitClock()
    private val identities = CommunitySpeakerIdentity(maxSpeakers)
    private val callbacks = DiarizationCallbackQueue()
    // Completed-window order only; model inputs stay in the client's evidence spool.
    private data class EvidenceWindow(val jobId: String, val windowStartSample: Long, val realEndSample: Long)
    private val windows = mutableListOf<EvidenceWindow>()
    private var totalSamples = 0L
    private var lastAsrEndMs = 0
    private var inferenceEndMs = 0
    private var processedThroughMs = 0
    private var previewThroughMs = 0
    private var publishedThrough = 0
    private var inferenceMs = 0L
    private var windowIndex = 0
    private var finalSpeakerCount = 0
    private var terminalPayload: SpeechRecognitionResult? = null
    private var decoratedTerminalPayload: SpeechRecognitionResult? = null
    private var degradedReason = SpeakerDiarizationDegradedReason.NONE
    private var degradedMessage: String? = null
    private var finishRequested = false
    private var confirmedInitialSilence = false
    private var processDrained = false
    private var asrTailObserved = false
    private var finished = false
    private var committing = false
    // Audio end covered by inferred windows when a finish timeout stopped inference.
    private var salvagedThroughMs: Int? = null

    init { require(maxSpeakers in 1..4) }

    @Synchronized
    override fun append(audio: ByteArray) {
        if (finishRequested || finished) return
        totalSamples += audio.size / 2
        client.append(audio)
    }

    override fun observeAsrFinal(payload: SpeechRecognitionResult, result: AsrResult): SpeechRecognitionResult {
        val decorated = synchronized(this) {
            if (payload.isLast) asrTailObserved = true
            val value = if (payload.result.isEmpty()) payload else {
                val timestamps = result.timestamps.map { (it * 1000).roundToInt() }
                val begin = payload.beginTime ?: timestamps.firstOrNull() ?: lastAsrEndMs
                val end = payload.endTime ?: timestamps.lastOrNull() ?: (totalSamples * 1000 / SAMPLE_RATE).toInt()
                lastAsrEndMs = maxOf(lastAsrEndMs, end)
                val id = transcript.addUtterance(result.rawText, payload.result, result.tokens, timestamps, begin, end,
                    ((ResultAudioTimeline.endSample(result) ?: totalSamples) * 1000 / SAMPLE_RATE).toInt())
                decoratePayloadLocked(payload.copy(utteranceId = id))
            }
            if (payload.isLast) terminalPayload = value
            flushReadyWindowsLocked()
            value
        }
        callbacks.drain()
        return decorated
    }

    override fun asrFinalDelivered(result: AsrResult) {
        synchronized(this) {
            if (finished || result.isLast) return
            val end = ResultAudioTimeline.endSample(result) ?: return
            if (diagnostic != null) recordDecision("DIARIZATION_ASR_ENDPOINT", mapOf("audioEndSample" to end))
            commitClock.observeEndpoint((end * 1000 / SAMPLE_RATE).toInt())
            flushReadyWindowsLocked()
        }
        callbacks.drain()
    }

    override fun asrAudioProcessed(endSample: Long) {
        synchronized(this) {
            if (finished) return
            processedThroughMs = maxOf(processedThroughMs, (endSample * 1000 / SAMPLE_RATE).toInt())
            if (diagnostic != null && processedThroughMs >= diagnosticProcessedMs + 10_000) {
                diagnosticProcessedMs = processedThroughMs
                recordDecision("DIARIZATION_ASR_PROCESSED", mapOf("audioEndSample" to endSample,
                    "appendedEndSample" to totalSamples, "inferenceEndMs" to inferenceEndMs))
            }
            commitClock.observeProcessedAudio(processedThroughMs)
            flushReadyWindowsLocked()
        }
        callbacks.drain()
    }

    override fun finish(confirmedInitialSilence: Boolean) {
        synchronized(this) {
            if (finishRequested || finished) return
            if (diagnostic != null) recordDecision("DIARIZATION_FINISH", mapOf("audioEndSample" to totalSamples,
                "processedThroughMs" to processedThroughMs, "inferenceEndMs" to inferenceEndMs))
            finishRequested = true
            this.confirmedInitialSilence = confirmedInitialSilence
            if (confirmedInitialSilence) {
                client.cancel()
                processDrained = true
                flushReadyWindowsLocked()
            } else client.finish()
        }
        callbacks.drain()
    }

    @Synchronized
    override fun decoratePayload(payload: SpeechRecognitionResult): SpeechRecognitionResult =
        if (payload.isLast) decoratedTerminalPayload ?: decoratePayloadLocked(payload) else decoratePayloadLocked(payload)

    private fun decoratePayloadLocked(payload: SpeechRecognitionResult): SpeechRecognitionResult {
        val assignment = payload.utteranceId?.let { transcript.currentAssignment(it) } ?: return payload
        return payload.copy(speakerIndex = speakerIndexFromInternalId(assignment.speakerId, maxSpeakers),
            secondarySpeakerIndexes = speakerIndexesFromInternalIds(assignment.secondarySpeakerIds, maxSpeakers, true),
            speakerConfidence = assignment.confidence)
    }

    @Synchronized
    override fun bestResult(reason: SpeakerDiarizationDegradedReason, message: String?): SpeakerDiarizationResult {
        if (reason != SpeakerDiarizationDegradedReason.NONE) transcript.applySpeakerTurns(emptyList(), true)
        return buildResultLocked(if (reason == SpeakerDiarizationDegradedReason.NONE) degradedReason else reason,
            message ?: degradedMessage)
    }

    override fun salvage() {
        synchronized(this) {
            // A drained session already owns a complete final commit; let it finish normally.
            if (finished || !finishRequested || processDrained || salvagedThroughMs != null) return
            salvagedThroughMs = inferenceEndMs
            if (diagnostic != null) recordDecision("DIARIZATION_FINISH_SALVAGE", mapOf(
                "inferenceEndMs" to inferenceEndMs, "audioEndSample" to totalSamples, "windows" to windows.size))
            client.stopInference()
            transcript.limitEvidence(inferenceEndMs)
            processDrained = true
            flushReadyWindowsLocked()
        }
        callbacks.drain()
    }

    @Synchronized
    override fun cancel(onQuiescent: (() -> Unit)?) {
        finished = true
        callbacks.close()
        client.cancel(onQuiescent)
    }

    @Synchronized
    fun cleanup(onQuiescent: (() -> Unit)? = null) {
        finished = true
        client.cleanup(onQuiescent)
    }

    override fun onWindow(result: DiarizationLocalWindowResult) {
        synchronized(this) {
            if (finished || confirmedInitialSilence || salvagedThroughMs != null) return
            if (diagnostic != null) recordDecision("DIARIZATION_COMMUNITY_WINDOW", mapOf(
                "jobId" to result.jobId, "windowStartSample" to result.windowStartSample,
                "realEndSample" to result.realEndSample, "segmentations" to result.result.segments,
                "embeddings" to result.result.embeddings, "segmentationMs" to result.result.segmentationMs,
                "featureMs" to result.result.featureMs, "embeddingMs" to result.result.embeddingMs,
                "runEmbeddings" to result.result.runEmbeddings, "runRanges" to result.result.runRanges,
                "runRms" to result.result.runRms,
                "appendedEndSample" to totalSamples, "processedThroughMs" to processedThroughMs))
            client.retainEvidence(result.result)
            windows += EvidenceWindow(result.jobId, result.windowStartSample, result.realEndSample)
            inferenceEndMs = (result.realEndSample * 1000 / SAMPLE_RATE).toInt()
            inferenceMs += (result.result.segmentationMs + result.result.featureMs + result.result.embeddingMs).toLong()
            flushReadyWindowsLocked()
        }
        callbacks.drain()
    }

    override fun onDrained() {
        synchronized(this) {
            if (!finishRequested || finished) return
            processDrained = true
            flushReadyWindowsLocked()
        }
        callbacks.drain()
    }

    override fun onDegraded(reason: SpeakerDiarizationDegradedReason, message: String) {
        synchronized(this) {
            if (finished || degradedReason != SpeakerDiarizationDegradedReason.NONE) return
            degradedReason = reason
            degradedMessage = message
            transcript.applySpeakerTurns(emptyList(), true)
        }
    }

    private data class Commit(val begin: Int, val end: Int, val evidenceEnd: Int,
        val final: Boolean = false, val provisional: Boolean = false)

    private fun flushReadyWindowsLocked() {
        if (finished || committing) return
        val progress = if (degradedReason == SpeakerDiarizationDegradedReason.NONE) inferenceEndMs else Int.MAX_VALUE
        val boundary = commitClock.takeReady(progress)
        val previewEnd = minOf(inferenceEndMs, processedThroughMs) / 10_000 * 10_000
        val commit = when {
            boundary != null -> Commit(boundary.beginTime, boundary.endTime, boundary.evidenceEndTime)
            finishRequested && processDrained && asrTailObserved ->
                Commit(publishedThrough, (totalSamples * 1000 / SAMPLE_RATE).toInt(), Int.MAX_VALUE, final = true)
            !finishRequested && degradedReason == SpeakerDiarizationDegradedReason.NONE &&
                lastAsrEndMs > publishedThrough && previewEnd >= maxOf(previewThroughMs, publishedThrough) + 10_000 -> {
                    previewThroughMs = previewEnd
                    Commit(publishedThrough, previewEnd, previewEnd, provisional = true)
                }
            else -> return
        }
        committing = true
        val available = windows.filter { commit.final ||
            (it.windowStartSample + 160_000) * 1000 / SAMPLE_RATE <= commit.evidenceEnd }
        if (confirmedInitialSilence || available.isEmpty() || degradedReason != SpeakerDiarizationDegradedReason.NONE) {
            completeCommitLocked(commit)
            committing = false
            flushReadyWindowsLocked()
            return
        }
        // Completed windows arrive in order; the evidence cutoff selects a prefix. Read
        // exactly that prefix, including history already frozen for callers (as Harmony).
        val evidence = try { client.readEvidence(available.size) } catch (t: Throwable) {
            onDegraded(SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE,
                "diarization evidence read failed: ${t.message ?: t.javaClass.simpleName}")
            completeCommitLocked(commit)
            committing = false
            flushReadyWindowsLocked()
            return
        }
        val segments = evidence.segments
        val publishedActivity = IntArray(available.size * 3)
        available.forEachIndexed { index, window ->
            for (frame in 0 until 589) {
                val time = (window.windowStartSample + 495.5 + frame * 270) * 1000 / SAMPLE_RATE
                if (time >= commit.begin && time < commit.end) for (channel in 0..2) {
                    publishedActivity[index * 3 + channel] += segments[(index * 589 + frame) * 3 + channel].toInt()
                }
            }
        }
        val started = System.nanoTime()
        client.cluster(segments, evidence.embeddings, maxSpeakers,
            available.map { it.windowStartSample.toDouble() }.toDoubleArray(),
            commit.begin.toDouble() * SAMPLE_RATE / 1000, evidence.runEmbeddings, evidence.runRanges,
            evidence.runRms) { outcome ->
            synchronized(this) {
                if (!finished) {
                    outcome.onSuccess { clustered ->
                        if (!confirmedInitialSilence && degradedReason == SpeakerDiarizationDegradedReason.NONE) {
                            inferenceMs += (System.nanoTime() - started) / 1_000_000
                            val visible = BooleanArray(clustered.speakerCount)
                            val firstAppearance = DoubleArray(clustered.speakerCount) { Double.POSITIVE_INFINITY }
                            clustered.turns.filter { it[0] < commit.end && it[1] > commit.begin }.forEach {
                                val label = it[2].toInt()
                                if (label in visible.indices) {
                                    visible[label] = true
                                    firstAppearance[label] = minOf(firstAppearance[label], maxOf(commit.begin.toDouble(), it[0]))
                                }
                            }
                            val registry = if (commit.provisional) identities.fork() else identities
                            val identity = registry.assign(available.map { it.jobId }, clustered.hard,
                                clustered.speakerCount, publishedActivity, visible, firstAppearance)
                            if (diagnostic != null) recordDecision(
                                if (commit.provisional) "DIARIZATION_COMMUNITY_PREVIEW" else "DIARIZATION_COMMUNITY_COMMIT",
                                mapOf("beginTime" to commit.begin, "endTime" to commit.end,
                                    "evidenceEndTime" to commit.evidenceEnd, "jobIds" to available.map { it.jobId },
                                    "windowStartSamples" to available.map { it.windowStartSample },
                                    "hard" to clustered.hard.toList(), "speakerCount" to clustered.speakerCount,
                                    "publishedActivity" to publishedActivity.toList(), "visibleClusters" to visible.toList(),
                                    "clusterToFrozenId" to identity.mapping.toList(), "registryBefore" to identity.before,
                                    "registryAfter" to identity.after, "clusterWallMs" to (System.nanoTime()-started)/1_000_000,
                                    "turns" to clustered.turns.map { it.toList() }))
                            if (!commit.provisional) finalSpeakerCount = identity.after
                            val turns = communityTimeline(clustered.turns, identity.mapping, commit.begin, commit.end)
                            transcript.applySpeakerTurns(turns, true).forEach { update ->
                                callbacks.enqueue { observer.onUpdate(update.toPublic()) }
                            }
                        }
                    }.onFailure {
                        onDegraded(SpeakerDiarizationDegradedReason.INFERENCE_UNAVAILABLE,
                            "Community finalization failed: ${it.message}")
                    }
                    completeCommitLocked(commit)
                }
                committing = false
            }
            // Let reentrant cancellation run before scheduling another commit.
            callbacks.drain()
            synchronized(this) { flushReadyWindowsLocked() }
            callbacks.drain()
        }
    }

    private fun completeCommitLocked(commit: Commit) {
        if (commit.provisional || finished) return
        terminalPayload?.let { decoratedTerminalPayload = decoratePayloadLocked(it) }
        val salvaged = salvagedThroughMs?.takeIf { commit.final && degradedReason == SpeakerDiarizationDegradedReason.NONE }
        val result = if (salvaged == null) buildResultLocked(degradedReason, degradedMessage, commit.end, commit.begin)
            else buildResultLocked(SpeakerDiarizationDegradedReason.FINISH_TIMEOUT,
                "speaker diarization finish timeout; speakers cover audio before ${salvaged}ms", commit.end, commit.begin)
        val committed = result.copy(isSessionFinal = commit.final)
        transcript.commitThrough(commit.end)
        publishedThrough = commit.end
        // Public commitment freezes display state, not the input distribution of the
        // unchanged batch clusterer. Evidence stays on disk until client cleanup.
        if (commit.final) {
            windows.clear()
            finished = true
            callbacks.enqueue { observer.onFinished(committed) }
        } else {
            if (committed.utterances.isNotEmpty() || committed.speakerTurns.isNotEmpty()) {
                windowIndex++
                callbacks.enqueue { observer.onWindowResult(committed) }
            }
        }
    }

    private fun buildResultLocked(
        reason: SpeakerDiarizationDegradedReason,
        message: String?,
        endTime: Int = (totalSamples * 1000 / SAMPLE_RATE).toInt(),
        beginTime: Int = publishedThrough,
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
        }
    }

    override fun asrAudioProcessed(endSample: Long) {
        synchronized(this) {
            if (finished) return
            commitClock.observeProcessedAudio((endSample * 1000 / SAMPLE_RATE).toInt())
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

    override fun finish(confirmedInitialSilence: Boolean) {
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
