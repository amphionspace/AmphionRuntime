package com.amphion.asr.internal

import kotlin.math.max
import kotlin.math.roundToInt
import kotlin.math.sqrt

/**
 * 按到达顺序给发言段分配说话人身份：声纹嵌入 + 增量质心。
 *
 * 为什么需要它：Sortformer 的四个槽位在"三人依次讲话"这类排列上会把不同的人并成一个
 * （主机实测 10 组只有 4 组正确，真机同口径 10/10 复现），而且是高置信度误并
 * （第 2 人在本该属于它的槽位上最大概率仅 0.030），调阈值、延长发言、全上下文重跑都无效。
 * 声纹嵌入在同一批材料上可分（同人最小 0.535、异人最大 0.338，余量 0.197），所以这里让
 * Sortformer 只管"何时有人说话"，身份改由嵌入决定。
 *
 * 本文件是**纯算术**：不读音频、不碰模型，嵌入由调用方给。与鸿蒙
 * `SpeakerIdentityAssigner.ts` 逐条镜像，常量必须一致。
 * 主机评测与定参见 `asr/tools/speaker/20_eval_campplus_identity_hybrid.py`。
 */
internal data class SpeakerIdentityDecision(
    /** 身份编号，或 [SpeakerIdentityAssigner.UNASSIGNED]。 */
    val identity: Int,
    /** 并入已有身份时为余弦相似度；新开身份时为 0（没有可比先验）。 */
    val confidence: Double,
)

internal class SpeakerIdentityAssigner(
    maxSpeakers: Int,
    private val threshold: Double = MERGE_THRESHOLD,
    minAssignSeconds: Double = MIN_ASSIGN_SECONDS,
) {
    private val maximumSpeakers = maxSpeakers.coerceAtLeast(1)
    private val minimumAssignSeconds = max(0.0, minAssignSeconds)
    private val centroids = mutableListOf<FloatArray>()
    private val counts = mutableListOf<Int>()

    /**
     * 处理一个发言段。必须按到达顺序调用：质心是增量更新的，顺序影响结果。
     *
     * @param embedding 该段的声纹嵌入；内部会再归一化一次，调用方不必保证。
     * @param durationSeconds 该段时长，短于 [MIN_ASSIGN_SECONDS] 则不赋身份。
     */
    fun assign(embedding: FloatArray, durationSeconds: Double): SpeakerIdentityDecision {
        if (durationSeconds < minimumAssignSeconds || embedding.isEmpty()) {
            return SpeakerIdentityDecision(UNASSIGNED, 0.0)
        }
        val e = normalized(embedding)
        var best = -1
        var score = -1.0
        for (index in centroids.indices) {
            val similarity = dot(centroids[index], e)
            if (similarity > score) {
                score = similarity
                best = index
            }
        }

        val slot: Int
        val confidence: Double
        if (best >= 0 && score >= threshold) {
            slot = best
            confidence = score
        } else if (centroids.size < maximumSpeakers) {
            centroids += e.copyOf()
            counts += 0
            slot = centroids.size - 1
            confidence = 0.0                 // 新开身份没有可比的先验
        } else {
            slot = best                      // 满员且都不够像，只能并入最近的
            confidence = max(0.0, score)
        }

        // 质心 = 历史均值与本段的归一化合成；count 从 0 起，所以首次更新后质心就是该段嵌入
        val centroid = centroids[slot]
        val merged = FloatArray(centroid.size)
        for (index in centroid.indices) {
            merged[index] = centroid[index] * counts[slot] + (if (index < e.size) e[index] else 0f)
        }
        counts[slot] = counts[slot] + 1
        centroids[slot] = normalized(merged)
        return SpeakerIdentityDecision(slot, confidence)
    }

    /** 已开出的身份数。 */
    fun identityCount(): Int = centroids.size

    /**
     * 清空。**不要**按 120 s 公共提交周期调用：质心必须在整个会话内保留，否则身份每个周期
     * 重新编号，那本身就是"角色错乱"的一种形态。只在会话结束时清。
     */
    fun reset() {
        centroids.clear()
        counts.clear()
    }

    private fun dot(a: FloatArray, b: FloatArray): Double {
        var sum = 0.0
        val n = minOf(a.size, b.size)
        for (index in 0 until n) sum += a[index].toDouble() * b[index]
        return sum
    }

    private fun normalized(v: FloatArray): FloatArray {
        var sum = 0.0
        for (value in v) sum += value.toDouble() * value
        val norm = sqrt(sum)
        if (norm <= 0.0) return v.copyOf()
        val out = FloatArray(v.size)
        for (index in v.indices) out[index] = (v[index] / norm).toFloat()
        return out
    }

    internal companion object {
        /**
         * 并入已有身份所需的最小余弦相似度。与鸿蒙 `IDENTITY_MERGE_THRESHOLD` 一致。
         *
         * 定参依据见鸿蒙侧同名常量的注释：客户现网 4 条在 0.35~0.50 均为 34/34，
         * 25 位真实会议说话人上 0.50 的合计错误率 0.346%（0.45 为 1.211%，且误并占 3.7 倍）。
         */
        const val MERGE_THRESHOLD = 0.50

        /**
         * 短于这个时长的发言段不赋身份、也不更新质心。
         *
         * 实测 1.0 s 门槛要牺牲 13% 的发言段换**零**准确率收益，故取 0.5 s（损 2%）。
         * 评测数据的参考段最短 1.27 s，测不出门槛本来要防的短段危害，所以保留一个低门槛
         * 而非去掉。
         */
        const val MIN_ASSIGN_SECONDS = 0.5

        /** 未赋身份。与公开 `speakerIndex` 的"不确定"取值一致。 */
        const val UNASSIGNED = -1
    }
}
