package com.amphion.asr.sample.eval

/**
 * 设备端「现场估算 WER」：字符级 Levenshtein 编辑距离 / 参考长度。
 *
 * 与后台权威 WER 的关系：
 * - 后台 [tools/asr/eval_wer.py] 用 jiwer 算"词级"WER，含 normalize / tokenize
 * - 这里是字符级，无 normalize，结果会高估错误率（尤其英文，词内一字母错就整词标错）
 * - 两个数字差异本身是有意义的信号：差距大说明 ITN / 标点 / 中英分词差异显著
 *
 * 故 UI 必须明确标注「现场估算（字符级）」，避免与后台报告混淆。
 *
 * 数值约定：
 * - 范围 [0.0, 1.0]，但极端情况下 hypothesis 比 reference 长很多时可能 > 1.0
 * - reference 为空时返回 1.0（hypothesis 任何内容都算"100% 错"）或 0.0（两者皆空）
 * - 永远不返回 NaN
 */
object DeviceWerEstimator {

    /**
     * 字符级 Levenshtein 距离。
     * 复杂度 O(n*m)，空间 O(min(n, m))。
     */
    fun editDistance(a: String, b: String): Int {
        if (a == b) return 0
        if (a.isEmpty()) return b.length
        if (b.isEmpty()) return a.length

        // 让 a 永远是较短的，节省空间
        val (s, t) = if (a.length <= b.length) a to b else b to a
        val n = s.length
        val m = t.length

        var prev = IntArray(n + 1) { it }
        var curr = IntArray(n + 1)

        for (j in 1..m) {
            curr[0] = j
            for (i in 1..n) {
                val cost = if (s[i - 1] == t[j - 1]) 0 else 1
                curr[i] = minOf(
                    curr[i - 1] + 1,         // insert
                    prev[i] + 1,             // delete
                    prev[i - 1] + cost,      // sub or match
                )
            }
            val tmp = prev
            prev = curr
            curr = tmp
        }
        return prev[n]
    }

    /**
     * 估算 WER。
     *
     * @param reference 参考文本（必须非空才有意义）
     * @param hypothesis 识别文本（可空 = 视为 100% 错）
     * @return 编辑距离 / 参考长度；超过 1.0 时也如实返回
     */
    fun estimate(reference: String, hypothesis: String?): Double {
        val ref = reference.trim()
        val hyp = (hypothesis ?: "").trim()
        if (ref.isEmpty() && hyp.isEmpty()) return 0.0
        if (ref.isEmpty()) return 1.0
        val dist = editDistance(ref, hyp)
        return dist.toDouble() / ref.length.toDouble()
    }

    /**
     * 把 WER 转成「准确率」百分比字符串，保留 1 位小数（"91.7%"）。
     *
     * 为什么 UI 上用准确率而非 WER：测试员不熟 WER 概念，"准确率 90%" 比 "WER 10%" 直观
     * 一万倍。schema / 后台脚本仍然用 WER；翻转只在展示层做。
     * 极端情况 WER > 1（hypothesis 比 reference 长很多），准确率会变成负数 —— 钳到 0。
     */
    fun formatPercent(wer: Double): String {
        val acc = (1.0 - wer).coerceAtLeast(0.0)
        return "%.1f%%".format(acc * 100.0)
    }
}
