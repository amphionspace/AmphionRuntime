package com.amphion.dingqiao.diarization

import kotlin.math.roundToInt

internal fun nmnetTimeline(tracks: List<DoubleArray>, mapping: IntArray,
    beginTime: Int, endTime: Int): List<SpeakerTimelineTurn> {
    val boundaries = mutableListOf(beginTime.toDouble(), endTime.toDouble())
    tracks.filter { it[0] < endTime && it[1] > beginTime }.forEach {
        boundaries += maxOf(beginTime.toDouble(), it[0]); boundaries += minOf(endTime.toDouble(), it[1])
    }
    val times = boundaries.distinct().sorted()
    val result = mutableListOf<SpeakerTimelineTurn>()
    var previous = ""
    times.zipWithNext().forEach { (begin, end) ->
        val active = tracks.filter { it[0] < end && it[1] > begin }
        val ids = active.map {
            val label = mapping.getOrNull(it[2].toInt()) ?: -1
            if (label >= 0) "S${label + 1}" else "UNKNOWN"
        }.distinct().sorted()
        if (ids.isEmpty()) { previous = ""; return@forEach }
        val primary = if (previous in ids) previous else ids.first()
        val secondary = ids.filter { it != primary }
        val overlap = active.size > 1
        val last = result.lastOrNull()
        val from = begin.roundToInt(); val through = end.roundToInt()
        if (through <= from) return@forEach
        if (last != null && last.endTime == from && last.speakerId == primary &&
            last.secondarySpeakerIds == secondary && last.overlap == overlap) {
            result[result.lastIndex] = last.copy(endTime = through)
        } else result += SpeakerTimelineTurn(from, through, primary, secondary, 0f, overlap)
        previous = primary
    }
    return result
}
