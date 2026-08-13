package com.amphion.asr.internal

import com.k2fsa.sherpa.onnx.SpeakerEmbeddingExtractor
import kotlin.math.sqrt

/**
 * 目标说话人声纹打分器（形态A 输出门控的算法核心）。
 *
 * 严格复刻 asr/tools/speaker/ts_asr/core.py 的加固逻辑（端侧与离线评测口径一致，才能直接复用
 * 调研期标定的阈值）：
 * - 多模板注册 [enroll]：多段 raw embedding 取均值后再 L2 归一（注意：不是每段先归一再均值，
 *   两者数学不等价；core.py 用的是 raw 均值 -> 归一）
 * - 滑窗多打分：段长 >= [winSec] 时按 [winSec]/[hopSec] 滑窗，取窗内 max 余弦（overlap 段
 *   embedding 被污染时，滑窗 max 比单次打分更稳）；不足 [winSec] 时回落整段单打
 * - 余弦判定：不用 SpeakerEmbeddingManager.verify 的单次 bool，因为需要滑窗取 max
 *
 * 线程模型：实例方法只在 [SessionImpl] 的 decoder 线程串行调用。[extractor] 为 engine 级共享，
 * 每次打分都新建一个临时 OnlineStream 并在用完后 release，无跨调用状态。
 */
internal class SpeakerVerifier(
    private val extractor: SpeakerEmbeddingExtractor,
    private val sampleRate: Int,
    private val winSec: Float,
    private val hopSec: Float,
) {

    /**
     * 对一段语音打目标说话人余弦相似度。
     *
     * ASR 已确认的 public final 即使短于严格评分门槛也尝试提取 embedding；短句精度风险由业务
     * 根据原始分数和自己的阈值承担。仅 extractor 在技术上尚未 ready 时返回 null。
     */
    fun segmentScore(samples: FloatArray, targetEmb: FloatArray): Float? {
        val nWin = (winSec * sampleRate).toInt()
        val nHop = (hopSec * sampleRate).toInt().coerceAtLeast(1)

        // 不够一个完整滑窗时仍使用整段真实 PCM 单次打分。
        if (samples.size < nWin) {
            val emb = extractEmbedding(extractor, samples, sampleRate) ?: return null
            return cosine(emb, targetEmb)
        }

        // 滑窗取窗内 max
        var best = -Float.MAX_VALUE
        var found = false
        var st = 0
        while (st + nWin <= samples.size) {
            val emb = extractEmbedding(extractor, samples.copyOfRange(st, st + nWin), sampleRate)
            if (emb != null) {
                val c = cosine(emb, targetEmb)
                if (c > best) best = c
                found = true
            }
            st += nHop
        }
        if (found) return best

        // 兜底（理论不触发）：整段单打
        val emb = extractEmbedding(extractor, samples, sampleRate) ?: return null
        return cosine(emb, targetEmb)
    }

    /**
     * 对一个实时滑窗打分。与 [segmentScore] 的“多窗取 max”不同，这里表示当前窗口本身是否像目标人，
     * 用于目标说话人离场检测。
     */
    fun windowScore(samples: FloatArray, targetEmb: FloatArray): Float? {
        val emb = extractEmbedding(extractor, samples, sampleRate) ?: return null
        return cosine(emb, targetEmb)
    }

    internal companion object {

        /**
         * 多模板注册：多段 raw embedding 取均值并 L2 归一。供 [SpeakerEnroller] 复用。
         *
         * @throws IllegalArgumentException segments 为空，或所有段都太短无法提 embedding
         */
        fun enroll(
            extractor: SpeakerEmbeddingExtractor,
            segments: List<FloatArray>,
            sampleRate: Int,
        ): FloatArray {
            require(segments.isNotEmpty()) { "enroll() needs at least 1 segment" }
            val dim = extractor.dim()
            val mean = FloatArray(dim)
            var count = 0
            for (seg in segments) {
                val emb = extractEmbedding(extractor, seg, sampleRate) ?: continue
                // raw 累加（与 core.py 一致：均值后再归一，而非每段先归一）
                val n = minOf(dim, emb.size)
                for (i in 0 until n) mean[i] += emb[i]
                count++
            }
            require(count > 0) {
                "enroll() failed: all ${segments.size} segment(s) too short to extract embedding"
            }
            val denom = count.toFloat()
            for (i in 0 until dim) mean[i] = mean[i] / denom
            return l2Normalize(mean)
        }

        /** 提单段 embedding（raw，未归一）；段太短导致 extractor 未 ready 时返回 null。 */
        private fun extractEmbedding(
            extractor: SpeakerEmbeddingExtractor,
            samples: FloatArray,
            sampleRate: Int,
        ): FloatArray? {
            val stream = extractor.createStream()
            return try {
                stream.acceptWaveform(samples, sampleRate)
                stream.inputFinished()
                if (!extractor.isReady(stream)) null else extractor.compute(stream)
            } finally {
                stream.release()
            }
        }

        /** 余弦相似度。两入参均不要求预先归一，分母含两者 L2 范数（与 core.py cosine 一致）。 */
        fun cosine(a: FloatArray, b: FloatArray): Float {
            val n = minOf(a.size, b.size)
            var dot = 0f
            var na = 0f
            var nb = 0f
            for (i in 0 until n) {
                dot += a[i] * b[i]
                na += a[i] * a[i]
                nb += b[i] * b[i]
            }
            val denom = (sqrt(na.toDouble()) * sqrt(nb.toDouble())).toFloat() + 1e-9f
            return dot / denom
        }

        /** L2 归一（加 1e-9 防零除，与 core.py _l2_normalize 一致）。 */
        fun l2Normalize(v: FloatArray): FloatArray {
            var s = 0f
            for (x in v) s += x * x
            val norm = sqrt(s.toDouble()).toFloat() + 1e-9f
            val out = FloatArray(v.size)
            for (i in v.indices) out[i] = v[i] / norm
            return out
        }
    }
}
