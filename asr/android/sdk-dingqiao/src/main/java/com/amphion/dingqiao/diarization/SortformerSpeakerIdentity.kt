package com.amphion.dingqiao.diarization

/** 槽位到公开角色编号的映射结果；`before`/`after` 是本次提交前后已公开的角色数。 */
internal data class SortformerIdentityMapping(
    /** 下标是槽位，值是公开角色编号（0 起），-1 表示 UNKNOWN。 */
    val mapping: IntArray,
    val before: Int,
    val after: Int,
) {
    override fun equals(other: Any?): Boolean =
        other is SortformerIdentityMapping && mapping.contentEquals(other.mapping) &&
            before == other.before && after == other.after

    override fun hashCode(): Int = mapping.contentHashCode() * 31 + before * 31 + after
}

/**
 * 四个 Sortformer 槽位的公开身份。与鸿蒙 `SortformerSpeakerIdentity.ts` 同一套规则。
 *
 * 模型自己按到达顺序排槽位并在整个会话内保持，所以这里不聚类、不重标注。这里只决定一个槽位
 * 什么时候成为公开角色：在它**首次于 final 块中发声**时，按首次发声顺序分配，至多
 * `maxSpeakers` 个。只在预览里出现过的槽位没有被说话人缓存确认，在它所属的块提交前保持
 * UNKNOWN；超出调用方上限的槽位按产品契约保持匿名。
 */
internal class SortformerSpeakerIdentity(private val maxSpeakers: Int) {
    private val slots = intArrayOf(-1, -1, -1, -1)
    private var nextId = 0

    /**
     * 提交 final 证据。`firstSpeechFrame[slot]` 是该槽位在刚收到的 final runs 里最早的发声帧，
     * 静默为 -1。并列与次序都按模型的槽位顺序，也就是到达顺序。
     */
    fun commit(firstSpeechFrame: IntArray): SortformerIdentityMapping {
        val before = nextId
        val order = slots.indices
            .filter { slots[it] < 0 && firstSpeechFrame.getOrElse(it) { -1 } >= 0 }
            .sortedWith(compareBy({ firstSpeechFrame[it] }, { it }))
        for (slot in order) {
            if (nextId >= maxSpeakers) break
            slots[slot] = nextId
            nextId += 1
        }
        return SortformerIdentityMapping(slots.copyOf(), before, nextId)
    }

    fun mapping(): IntArray = slots.copyOf()

    fun publishedCount(): Int = nextId
}
