package com.amphion.dingqiao.diarization

/**
 * 并发的逐人轨道变成 SDK 的不重叠时间线。与鸿蒙 `SpeakerTimeline.ts` 同一套规则：
 * 每个边界开一段 turn，主说话人优先延续上一段，其余进 secondary，一条轨道都不丢。
 */
internal data class SortformerTrack(val beginTime: Long, val endTime: Long, val slot: Int)

internal data class TimelineTurn(
    val beginTime: Long,
    var endTime: Long,
    val speakerId: String,
    val secondarySpeakerIds: List<String>,
    val confidence: Double = 0.0,
    val overlap: Boolean = false,
)

/** 把并发轨道切成时间线，范围限定在 [beginTime, endTime)。 */
internal fun timelineTurns(
    tracks: List<SortformerTrack>,
    mapping: IntArray,
    beginTime: Long,
    endTime: Long,
): List<TimelineTurn> {
    val boundaries = sortedSetOf(beginTime, endTime)
    for (track in tracks) {
        if (track.beginTime >= endTime || track.endTime <= beginTime) continue
        boundaries.add(maxOf(beginTime, track.beginTime))
        boundaries.add(minOf(endTime, track.endTime))
    }
    val ordered = boundaries.toList()
    val result = mutableListOf<TimelineTurn>()
    var previous = ""
    for (index in 1 until ordered.size) {
        val begin = ordered[index - 1]
        val end = ordered[index]
        val covering = tracks.filter { it.beginTime < end && it.endTime > begin }
        if (covering.isEmpty()) {
            previous = ""
            continue
        }
        val ids = covering
            .map { track ->
                val label = mapping.getOrElse(track.slot) { -1 }
                if (label >= 0) "S${label + 1}" else "UNKNOWN"
            }
            .distinct()
            .sorted()
        val primary = if (ids.contains(previous)) previous else ids.first()
        val secondary = ids.filter { it != primary }
        val overlap = covering.size > 1
        val last = result.lastOrNull()
        if (last != null && last.endTime == begin && last.speakerId == primary &&
            last.secondarySpeakerIds == secondary && last.overlap == overlap
        ) {
            last.endTime = end
        } else {
            result.add(
                TimelineTurn(
                    beginTime = begin,
                    endTime = end,
                    speakerId = primary,
                    secondarySpeakerIds = secondary,
                    overlap = overlap,
                ),
            )
        }
        previous = primary
    }
    return result
}
