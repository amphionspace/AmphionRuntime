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
