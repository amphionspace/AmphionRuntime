package com.amphion.dingqiao.diarization

/**
 * 并发的逐人轨道变成 SDK 的不重叠时间线。与鸿蒙 `SpeakerTimeline.ts` 同一套规则：
 * 每个边界开一段 turn，主说话人优先延续上一段，其余进 secondary，一条轨道都不丢。
 *
 * 直接产出转写状态已有的 [SpeakerTimelineTurn]（毫秒为 Int），不再额外定义一种 turn 类型。
 *
 * 为什么要支持"按段携带身份"：Sortformer 的槽位会把不同的人并进同一个槽位（依次发言场景
 * 主机 4/10、真机同口径 10/10 复现），而槽位→公开 id 的映射无法拆开同槽的两个人。声纹身份
 * 是按发言段判的，所以 [SortformerTrack.identity] 非空时优先用它；为空时回落到槽位映射，
 * 关闭声纹身份时行为与原先完全一致。
 */
internal data class SortformerTrack(
    val beginTime: Long,
    val endTime: Long,
    val slot: Int,
    /**
     * 声纹身份（开启 speakerIdentityMode 时由 SpeakerIdentityAssigner 给出）。null 表示未启用，
     * 按槽位映射；[SpeakerIdentityResolver.UNRESOLVED] 表示该段未赋身份（例如短于最小时长、
     * 取不到音频），照实落到 UNKNOWN，不猜。
     */
    var identity: Int? = null,
)

/** 把并发轨道切成时间线，范围限定在 [beginTime, endTime)。 */
internal fun timelineTurns(
    tracks: List<SortformerTrack>,
    mapping: IntArray,
    beginTime: Long,
    endTime: Long,
): List<SpeakerTimelineTurn> {
    val boundaries = sortedSetOf(beginTime)
    if (endTime != Long.MAX_VALUE) boundaries.add(endTime)
    for (track in tracks) {
        if (track.beginTime >= endTime || track.endTime <= beginTime) continue
        boundaries.add(maxOf(beginTime, track.beginTime))
        boundaries.add(minOf(endTime, track.endTime))
    }
    val ordered = boundaries.toList()
    val result = mutableListOf<SpeakerTimelineTurn>()
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
                val slotLabel = mapping.getOrElse(track.slot) { -1 }
                val label = track.identity ?: slotLabel
                if (label >= 0) "S${label + 1}" else "UNKNOWN"
            }
            .distinct()
            .sorted()
        // 只按槽位映射得到的身份，与 speakerId 并行算出；关闭声纹身份时两者相同。
        val modelIds = covering
            .map { track ->
                val slotLabel = mapping.getOrElse(track.slot) { -1 }
                if (slotLabel >= 0) "S${slotLabel + 1}" else "UNKNOWN"
            }
            .distinct()
            .sorted()
        val primary = if (ids.contains(previous)) previous else ids.first()
        val secondary = ids.filter { it != primary }
        val modelPrimary = modelIds.first()
        val overlap = covering.size > 1
        val last = result.lastOrNull()
        // 合并相邻片段时也要比 modelSpeakerId：否则一个 turn 会横跨不同的模型槽位，
        // 那个字段就失去对比价值了。
        if (last != null && last.endTime.toLong() == begin && last.speakerId == primary &&
            last.secondarySpeakerIds == secondary && last.overlap == overlap &&
            last.modelSpeakerId == modelPrimary
        ) {
            // SpeakerTimelineTurn.endTime 不可变：用延长后的副本替换最后一段。
            result[result.lastIndex] = last.copy(endTime = end.toInt())
        } else {
            result.add(
                SpeakerTimelineTurn(
                    beginTime = begin.toInt(),
                    endTime = end.toInt(),
                    speakerId = primary,
                    secondarySpeakerIds = secondary,
                    overlap = overlap,
                    modelSpeakerId = modelPrimary,
                ),
            )
        }
        previous = primary
    }
    return result
}
