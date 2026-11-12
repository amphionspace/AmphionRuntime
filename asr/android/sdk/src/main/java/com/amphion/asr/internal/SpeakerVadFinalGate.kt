package com.amphion.asr.internal

internal fun shouldScoreSpeakerFinal(
    targetSpeakerEnabled: Boolean,
    speakerVadEnabled: Boolean,
): Boolean = targetSpeakerEnabled || speakerVadEnabled

/** A real terminal score may confirm a short utterance before streaming Speaker VAD has a window. */
internal fun shouldRejectSpeakerVadFinal(
    enabled: Boolean,
    rejectCurrent: Boolean,
    targetConfirmed: Boolean,
    finalTargetMatch: Boolean?,
): Boolean = enabled && (rejectCurrent || (!targetConfirmed && finalTargetMatch != true))

/**
 * Whether the streaming speaker-turn detector must run.
 *
 * Speaker VAD keeps its original semantics. Target-speaker identification alone also needs the
 * detector: without it a speaker switch that happens without an endpoint silence puts both
 * speakers into one utterance, and the single terminal score is then dominated by whoever talked
 * longer, so the other speaker's words are published as the target's. The detector stays off when
 * no target is enrolled or the session has no scoring window config, because it cannot decide then.
 */
internal fun shouldRunSpeakerTurnDetection(
    speakerVadEnabled: Boolean,
    targetSpeakerEnabled: Boolean,
    hasTargetEmbedding: Boolean,
    hasWindowConfig: Boolean,
): Boolean = speakerVadEnabled ||
    (targetSpeakerEnabled && hasTargetEmbedding && hasWindowConfig)
