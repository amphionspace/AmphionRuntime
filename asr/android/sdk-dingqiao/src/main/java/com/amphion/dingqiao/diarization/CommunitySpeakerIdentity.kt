package com.amphion.dingqiao.diarization

import kotlin.math.roundToInt

internal data class CommunityIdentityAssignment(val mapping: IntArray, val before: Int, val after: Int)

/** Frozen identities are owned by acoustic window IDs, never by retained array positions. */
internal class CommunitySpeakerIdentity(private val maxSpeakers: Int) {
    private val committedIds = linkedMapOf<String, Int>()
    private val committedActivity = linkedMapOf<String, Int>()
    private var nextId = 0

    fun fork() = CommunitySpeakerIdentity(maxSpeakers).also {
        it.committedIds.putAll(committedIds)
        it.committedActivity.putAll(committedActivity)
        it.nextId = nextId
    }

    fun assign(windowIds: List<String>, hard: IntArray, clusterCount: Int,
        publishedActivity: IntArray, visibleClusters: BooleanArray,
        firstAppearanceTimes: DoubleArray? = null): CommunityIdentityAssignment {
        val before = nextId
        val votes = Array(clusterCount) { IntArray(before) }
        val keys = hard.indices.map { "${windowIds[it / 3]}:${it % 3}" }
        hard.indices.forEach { index ->
            val old = committedIds[keys[index]] ?: -1
            if (old >= 0 && hard[index] >= 0) votes[hard[index]][old] += committedActivity[keys[index]] ?: 0
        }
        var bestScore = -1
        var best = IntArray(clusterCount) { -1 }
        val current = best.copyOf()
        fun visit(cluster: Int, used: Int, score: Int) {
            if (cluster == clusterCount) {
                if (score > bestScore) { bestScore = score; best = current.copyOf() }
                return
            }
            for (id in 0 until before) {
                if (used and (1 shl id) != 0 || votes[cluster][id] <= 0) continue
                current[cluster] = id
                visit(cluster + 1, used or (1 shl id), score + votes[cluster][id])
            }
            current[cluster] = -1
            visit(cluster + 1, used, score)
        }
        visit(0, 0, 0)
        // Only allocate new IDs chronologically, as on Harmony. Existing committed
        // identities keep their IDs even if later evidence moves an earlier boundary.
        val appearanceOrder = (0 until clusterCount).sortedWith(compareBy<Int> {
            firstAppearanceTimes?.getOrNull(it) ?: Double.POSITIVE_INFINITY
        }.thenBy { it })
        for (cluster in appearanceOrder) {
            val hasActivity = visibleClusters[cluster] && hard.indices.any {
                hard[it] == cluster && publishedActivity[it] > 0
            }
            if (hasActivity && best[cluster] < 0 && nextId < maxSpeakers) best[cluster] = nextId++
        }
        hard.indices.forEach { index ->
            val cluster = hard[index]
            if (keys[index] !in committedIds && cluster >= 0 && best[cluster] >= 0 &&
                publishedActivity[index] > 0 && visibleClusters[cluster]) {
                committedIds[keys[index]] = best[cluster]
                committedActivity[keys[index]] = publishedActivity[index]
            }
        }
        return CommunityIdentityAssignment(best, before, nextId)
    }
}

internal fun communityTimeline(tracks: List<DoubleArray>, mapping: IntArray,
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
