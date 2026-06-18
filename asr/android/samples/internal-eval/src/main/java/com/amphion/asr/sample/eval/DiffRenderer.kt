package com.amphion.asr.sample.eval

import android.content.Context
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.style.BackgroundColorSpan
import androidx.core.content.ContextCompat
import com.amphion.asr.sample.R

/**
 * 用 LCS 对齐 reference vs hypothesis 并渲染三色 diff（绿匹配 / 黄替换 / 红插入删除）。
 *
 * 算法：
 * 1. 用经典 LCS DP 求两个字符串的最长公共子序列长度表
 * 2. 回溯生成操作序列：MATCH / SUB / DEL / INS（DEL = reference 多出来；INS = hypothesis 多出来）
 * 3. 把 reference 与 hypothesis 分别渲染：
 *    - reference 行：MATCH 绿、SUB 黄、DEL 红删除线
 *    - hypothesis 行：MATCH 绿、SUB 黄、INS 红
 *
 * 复杂度 O(n*m)，对一句话 < 50 字符无压力；对 200 字符长句也 < 1ms。
 *
 * Roast 说明：
 * - 中文是逐 char 对齐，对"今天天气"vs"今晚天气"会标"今[绿]天[黄]天[绿]气[绿]"
 *   而非按词对齐。这是设备端"现场估算"，不与后台 jiwer 词级 WER 冲突
 * - 英文也是逐 char 对齐，会高估错误率（一个单词错一个字母 = 整个单词标红）；
 *   后台权威 WER 仍按词级算，差异本身有意义
 */
object DiffRenderer {

    /** 三色 background 色资源，定义在 res/values/colors.xml。 */
    private val COLOR_MATCH = R.color.eval_diff_match
    private val COLOR_SUB = R.color.eval_diff_sub
    private val COLOR_DEL = R.color.eval_diff_del
    private val COLOR_INS = R.color.eval_diff_ins

    enum class Op { MATCH, SUB, DEL, INS }

    /** 一步操作；SUB / DEL 含 refChar，SUB / INS 含 hypChar，MATCH 两者相等。 */
    data class Step(val op: Op, val refChar: Char?, val hypChar: Char?)

    /** reference 行渲染（保留 reference 字符顺序，INS 不出现；DEL 用 ref char 渲染红 BG）。 */
    fun renderReference(ctx: Context, ref: String, hyp: String): CharSequence {
        if (ref.isEmpty()) return ""
        val steps = align(ref, hyp)
        val sb = SpannableStringBuilder()
        for (s in steps) {
            when (s.op) {
                Op.MATCH -> append(sb, s.refChar!!, ctx, COLOR_MATCH)
                Op.SUB -> append(sb, s.refChar!!, ctx, COLOR_SUB)
                Op.DEL -> append(sb, s.refChar!!, ctx, COLOR_DEL)
                Op.INS -> Unit
            }
        }
        return sb
    }

    /** hypothesis 行渲染（保留 hyp 字符顺序，DEL 不出现；INS 用 hyp char 渲染红 BG）。 */
    fun renderHypothesis(ctx: Context, ref: String, hyp: String): CharSequence {
        if (hyp.isEmpty()) return ""
        val steps = align(ref, hyp)
        val sb = SpannableStringBuilder()
        for (s in steps) {
            when (s.op) {
                Op.MATCH -> append(sb, s.hypChar!!, ctx, COLOR_MATCH)
                Op.SUB -> append(sb, s.hypChar!!, ctx, COLOR_SUB)
                Op.INS -> append(sb, s.hypChar!!, ctx, COLOR_INS)
                Op.DEL -> Unit
            }
        }
        return sb
    }

    /**
     * LCS 对齐并回溯生成 Step 序列。
     * 注意：这里实现的是 LCS-based diff，不是 Levenshtein 最优 path；
     * 对 WER 估算够用，对人眼可读 diff 也直观。
     */
    fun align(ref: String, hyp: String): List<Step> {
        val r = ref.length
        val h = hyp.length
        if (r == 0 && h == 0) return emptyList()
        if (r == 0) return hyp.map { Step(Op.INS, null, it) }
        if (h == 0) return ref.map { Step(Op.DEL, it, null) }

        // dp[i][j] = LCS length of ref[..i] vs hyp[..j]
        val dp = Array(r + 1) { IntArray(h + 1) }
        for (i in 1..r) for (j in 1..h) {
            dp[i][j] = if (ref[i - 1] == hyp[j - 1]) dp[i - 1][j - 1] + 1
            else maxOf(dp[i - 1][j], dp[i][j - 1])
        }

        // 回溯：优先 MATCH，再 SUB（dp[i-1][j-1] 不增长但两边都消耗 = 替换），
        // 再 DEL / INS。
        val out = ArrayList<Step>(r + h)
        var i = r
        var j = h
        while (i > 0 && j > 0) {
            when {
                ref[i - 1] == hyp[j - 1] -> {
                    out.add(Step(Op.MATCH, ref[i - 1], hyp[j - 1]))
                    i--; j--
                }
                dp[i - 1][j] >= dp[i][j - 1] && dp[i][j - 1] >= dp[i - 1][j - 1] -> {
                    // 当 dp[i-1][j] == dp[i][j-1] == dp[i-1][j-1] 时优先 SUB（视觉上更紧凑）
                    if (dp[i - 1][j] == dp[i][j - 1] && dp[i - 1][j] == dp[i - 1][j - 1]) {
                        out.add(Step(Op.SUB, ref[i - 1], hyp[j - 1]))
                        i--; j--
                    } else {
                        out.add(Step(Op.DEL, ref[i - 1], null))
                        i--
                    }
                }
                dp[i - 1][j] > dp[i][j - 1] -> {
                    out.add(Step(Op.DEL, ref[i - 1], null))
                    i--
                }
                else -> {
                    out.add(Step(Op.INS, null, hyp[j - 1]))
                    j--
                }
            }
        }
        while (i > 0) {
            out.add(Step(Op.DEL, ref[i - 1], null))
            i--
        }
        while (j > 0) {
            out.add(Step(Op.INS, null, hyp[j - 1]))
            j--
        }
        out.reverse()
        return out
    }

    private fun append(sb: SpannableStringBuilder, ch: Char, ctx: Context, colorRes: Int) {
        val start = sb.length
        sb.append(ch)
        val span = BackgroundColorSpan(ContextCompat.getColor(ctx, colorRes))
        sb.setSpan(span, start, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
    }
}
