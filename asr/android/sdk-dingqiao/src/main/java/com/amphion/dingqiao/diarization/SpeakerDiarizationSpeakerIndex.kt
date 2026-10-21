package com.amphion.dingqiao.diarization

internal fun speakerIndexFromInternalId(speakerId: String, maxSpeakers: Int): Int {
    if (!speakerId.startsWith("S")) return -1
    val oneBased = speakerId.substring(1).toIntOrNull() ?: return -1
    return if (oneBased > 0 && (maxSpeakers == 0 || oneBased <= maxSpeakers)) oneBased - 1 else -1
}

internal fun speakerIndexesFromInternalIds(
    speakerIds: List<String>,
    maxSpeakers: Int,
    excludeUnknown: Boolean,
): List<Int> = speakerIds.map { speakerIndexFromInternalId(it, maxSpeakers) }
    .filter { !excludeUnknown || it >= 0 }
    .distinct()
