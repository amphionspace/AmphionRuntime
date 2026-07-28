package com.amphion.police.terms

import android.content.Context
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * 警务术语后处理 **V2**（与派出所 [com.amphion.police.station.PoliceStationNormalizerV2] 同骨架）。
 *
 * 术语场景**没有「派出所」那样的天然边界锚**，且含大量 2–3 字短词（警情/处警/帮填…），
 * 直接全局模糊纠极易过纠。故 V2 接受门显著收紧，且分两档（与派出所 V2 同思路：等长优先、变长兜底）：
 * 1. 先复用 V1 全局谐音替换（[PoliceTermsHomophoneDict.applyPhrases]）做安全的人工高置信纠正；
 * 2. 再叠加**保守**的「字级候选格 ∩ gazetteer 校验器」模糊层：
 *    - 第一档（主）：长度 ≥ [minFuzzyLen] 的术语做**等长纯近音替换**，替换数 ≤ [maxSubsFor]；
 *    - 第二档（变长兜底）：仅当第一档在该位置无唯一解时才尝试，处理上游多/漏一字的误识：
 *      长度 ≥ [minVarLen]、**只允许 1 次增删字**（|Δ长度| = 1）、其余位仍须近音、总编辑 ≤ [maxSubsFor]；
 *    - 两档都要求同位置能匹配的标准术语**唯一**，并列即放弃（不臆造）。
 *
 * V1 文件完全未改，可随时切回（[PoliceTermsEnhancePrefs.termsV2Enabled]）。
 */
class PoliceTermsNormalizerV2 private constructor(
    private val homophones: PoliceTermsHomophoneDict,
    private val gazetteer: PoliceTermsGazetteer,
    private val terms: List<String>,
    private val readingMap: TermReadingMap,
) {

    /** 低于此长度的术语不做模糊纠正（只精确匹配），避免 2–3 字短词过纠。 */
    private val minFuzzyLen = 4

    /**
     * 变长兜底（增删字）的最小术语长度。比 [minFuzzyLen] 更严：对 4 字术语增删一字风险过高，
     * 故仅长度 ≥ 5 的术语才允许变长纠正。
     */
    private val minVarLen = 5

    /** 模糊层每个术语允许的最大编辑数（按长度放缩）；变长兜底里 1 次增删也计入此预算。 */
    private fun maxSubsFor(len: Int): Int = if (len >= 7) 2 else 1

    companion object {
        private const val GAZETTEER_ASSET = "police_terms/term_gazetteer.txt"

        /** 身份证号/号码为 后的数字串里去掉空格（允许中间已有冒号）。 */
        private val ID_DIGIT_SPACES = Regex(
            "(身份证号|号码为|身份证号码为)[：:]?([0-9][0-9 ]{14,30})",
        )

        /**
         * 语音指令「核查/查检车牌号」后的紧凑车牌：川AF60080 / 川AF 60080 / 川A F60080 → 川A F60080。
         */
        private val PLATE_CMD_COMPACT = Regex(
            "((?:帮我)?(?:核查|查检)车牌号)[：:，,]?(川)([A-HJ-NP-Z])\\s*([A-HJ-NP-Z])\\s*([0-9]{5})",
        )

        /**
         * 用 + WeCom误识族 + 向/想。误识族含：VCOM/VCOOM/V COM、Weconmm/WeConmm/WeComm、微COM、维康姆。
         */
        private val WECOM_AFTER_YONG = Regex(
            "用\\s*(?i:v\\s*c+o+m+|we\\s*c+o+n*m+|微\\s*com|维康姆)\\s*(?:想|向)",
        )

        /** WeCom误识族紧跟「向…」或「发起呼叫」。 */
        private val WECOM_BEFORE_CALL = Regex(
            "(?i)(v\\s*c+o+m+|we\\s*c+o+n*m+)(\\s*(?:向|发起呼叫))",
        )

        fun create(context: Context): PoliceTermsNormalizerV2 {
            val terms = context.assets.open(GAZETTEER_ASSET).use { input ->
                BufferedReader(InputStreamReader(input, Charsets.UTF_8)).readLines()
                    .map { it.trim() }
                    .filter { it.isNotEmpty() && !it.startsWith("#") }
                    .distinct()
                    .sortedByDescending { it.length }
            }
            return PoliceTermsNormalizerV2(
                PoliceTermsHomophoneDict.load(context),
                PoliceTermsGazetteer.load(context),
                terms,
                TermReadingMap.load(context),
            )
        }

        internal fun create(
            homophones: PoliceTermsHomophoneDict,
            gazetteer: PoliceTermsGazetteer,
            terms: List<String>,
            readingMap: TermReadingMap,
        ): PoliceTermsNormalizerV2 = PoliceTermsNormalizerV2(homophones, gazetteer, terms, readingMap)
    }

    fun normalize(text: String): PoliceTermsNormalizeResult {
        if (text.isEmpty()) return PoliceTermsNormalizeResult(text, emptyList())

        // 1) 复用 V1 全局谐音（高置信人工对），保证不回退。
        val global = homophones.applyPhrases(text)
        // 1.5) 「情指行」上下文护栏纠正：仅在 App 语境下把 请指信/停止行/停止航 纠回 情指行，
        //      并排除 停止行动/停止航班/请指信息 等碰撞词，避免误伤通用句子。
        val guarded = applyQingZhiXingGuard(global)
        // 1.6) 「登录」上下文护栏：仅在登录语境（后随 系统/平台/门户/客户端… ）下把 登陆 纠回 登录，
        //      排除 登陆作战/抢滩登陆/台风登陆沿海 等通用义，避免误伤。
        val guarded2 = applyDengluGuard(guarded)
        // 2) 叠加保守模糊层（仅长术语、等长近音、唯一）。
        val fuzzy = fuzzyCorrect(guarded2)
        // 3) 电台音标数字归一（洞0幺1两2拐7勾9…），严格数字上下文门控。
        val corrected = PoliceTermsRadioDigits.normalize(fuzzy)
        // 4) 指令格式润色 + 再跑一遍谐音（供身份证空格合并、车牌号格式等落地）。
        val polished = polish(corrected)
        val spans = locateSpans(polished)
        return PoliceTermsNormalizeResult(polished, spans)
    }

    /**
     * 管线末段润色（车牌/派出所之后再调一次）：合并证件号空格、规范语音指令里的车牌书写，
     * 并再应用谐音表（例如把「号码为3705…」补成「，号码为：3705…」）。
     */
    fun polish(text: String): String {
        if (text.isEmpty()) return text
        val formatted = formatVoiceCommands(text)
        return homophones.applyPhrases(formatted)
    }

    /**
     * 语音指令格式归一（不做模糊匹配，避免再删虚词）：
     * - 身份证号语境下去掉数字间空格；
     * - 「核查/查检车牌号」后的 川AF60080 / 川A F60080 → 川A F60080，并补冒号；
     * - WeCom 英文误识族（VCOM/Weconmm/…）大小写不敏感收成 WeCom。
     */
    private fun formatVoiceCommands(text: String): String {
        var t = text
        t = ID_DIGIT_SPACES.replace(t) { m ->
            val prefix = m.groupValues[1]
            val digits = m.groupValues[2].replace(" ", "")
            // 统一成「前缀：数字」，与甲方指令书写一致
            "$prefix：$digits"
        }
        t = PLATE_CMD_COMPACT.replace(t) { m ->
            val prefix = m.groupValues[1]
            val prov = m.groupValues[2]
            val city = m.groupValues[3]
            val serial = m.groupValues[4]
            val digits = m.groupValues[5]
            "$prefix：$prov$city $serial$digits"
        }
        t = normalizeWeComNames(t)
        return t
    }

    /**
     * WeCom 产品名归一。谐音 CSV 对大小写敏感，真人/ASR 常出 VCOM、Weconmm、WE COM 等，
     * 在「用…向/想」或「…向/发起呼叫」锚点下做大小写不敏感替换。
     */
    private fun normalizeWeComNames(text: String): String {
        var t = text
        // 用 VCOM/Weconmm/微COM/维康姆 向|想 → 用WeCom向
        t = WECOM_AFTER_YONG.replace(t) { "用WeCom向" }
        // 句中裸写：VCOM向 / Weconmm发起呼叫
        t = WECOM_BEFORE_CALL.replace(t) { "WeCom${it.groupValues[2]}" }
        return t
    }

    /**
     * 「情指行」误识变体（真人/TTS 常见），值为「碰撞后继字」黑名单：
     * 变体后紧跟这些字时说明是通用词（如 停止行→动/为、停止航→班/行、请指信→息），一律不纠。
     */
    private val qingZhiXingVariants: Map<String, Set<Char>> = mapOf(
        "请指信" to setOf('息'),
        // 请执行=通用高频词，只在 App 语境（打开X/…平台）下纠；后紧跟 命令/任务/操作/结果/判决… 等真·动宾字时不纠。
        // 注：不含 的/了/过 等虚词——「打开请执行的X」里 打开 已是强 App 信号，的 只是误识尾巴，应纠。
        "请执行" to setOf('命', '任', '操', '程', '死', '判', '完', '以', '方', '决', '计', '结'),
        "停止行" to setOf('动', '为', '走', '驶', '车', '列', '进'),
        "停止航" to setOf('班', '行', '道', '向', '线'),
    )

    /** 变体前的「打开类」动词触发（允许中间夹一个标点）。 */
    private val qingZhiXingOpenVerbs = listOf("打开", "登录", "进入", "启动", "点击", "使用")

    /** 变体后近窗内的 App 语境词触发。 */
    private val qingZhiXingAppCtx =
        listOf("客户端", "平台", "系统", "首页", "模块", "上报", "签收", "下发", "指令", "勤务", "版本", "核心")

    /**
     * 上下文受限地把 情指行 的误识变体纠回。命中条件（且未撞黑名单后继字）：
     * 变体后 5 字窗口内出现 App 语境词，或变体前紧邻打开类动词（可夹一个标点）。
     */
    private fun applyQingZhiXingGuard(text: String): String {
        if (text.length < 3) return text
        var out = text
        for ((variant, neg) in qingZhiXingVariants) {
            if (!out.contains(variant)) continue
            val sb = StringBuilder(out.length)
            var i = 0
            while (i <= out.length) {
                val idx = out.indexOf(variant, i)
                if (idx < 0) {
                    sb.append(out, i, out.length)
                    break
                }
                sb.append(out, i, idx)
                val end = idx + variant.length
                val after = out.getOrNull(end)
                val collide = after != null && after in neg
                val ctxAfter = out.substring(end, (end + 5).coerceAtMost(out.length))
                val hasAfterCtx = qingZhiXingAppCtx.any { ctxAfter.contains(it) }
                val before = out.substring(0, idx)
                val hasOpenVerb = qingZhiXingOpenVerbs.any {
                    before.endsWith(it) ||
                        before.endsWith("$it，") || before.endsWith("$it,") || before.endsWith("$it、")
                }
                sb.append(if (!collide && (hasAfterCtx || hasOpenVerb)) "情指行" else variant)
                i = end
            }
            out = sb.toString()
        }
        return out
    }

    /** 「登录」误识 登陆 的登录语境词（近窗触发）。 */
    private val dengluCtx = listOf(
        "系统", "平台", "客户端", "门户", "账号", "帐号", "后台",
        "应用", "界面", "首页", "模块", "网站", "网页",
    )

    /** 登陆 后紧跟这些字时是通用义（登陆作战/舰/艇/沿海/岛/部队/战役/地点），一律不纠。 */
    private val dengluCollide = setOf('作', '演', '舰', '艇', '部', '战', '岛', '滩', '沿', '海', '月')

    /**
     * 上下文受限地把「登陆」纠回「登录」：仅当其后近窗（6 字内）出现登录语境词、
     * 且紧邻后继字不在 [dengluCollide] 黑名单时才替换。
     */
    private fun applyDengluGuard(text: String): String {
        if (!text.contains("登陆")) return text
        val variant = "登陆"
        val sb = StringBuilder(text.length)
        var i = 0
        while (i <= text.length) {
            val idx = text.indexOf(variant, i)
            if (idx < 0) {
                sb.append(text, i, text.length)
                break
            }
            sb.append(text, i, idx)
            val end = idx + variant.length
            val after = text.getOrNull(end)
            val collide = after != null && after in dengluCollide
            val ctxAfter = text.substring(end, (end + 6).coerceAtMost(text.length))
            val hasCtx = dengluCtx.any { ctxAfter.contains(it) }
            sb.append(if (!collide && hasCtx) "登录" else variant)
            i = end
        }
        return sb.toString()
    }

    /** 命中的标准术语 + 它在原文里实际吃掉的字数（等长档 = 术语长度；变长档可能 ±1）。 */
    private data class TermMatch(val term: String, val consumed: Int)

    /** 从左到右扫描，把「距某标准术语 ≤ 预算且唯一」的窗口纠正为该术语。 */
    private fun fuzzyCorrect(text: String): String {
        val sb = StringBuilder(text.length)
        var i = 0
        while (i < text.length) {
            val hit = bestTermAt(text, i)
            if (hit != null) {
                sb.append(hit.term)
                i += hit.consumed
            } else {
                sb.append(text[i])
                i++
            }
        }
        return sb.toString()
    }

    /**
     * 在 [start] 处选标准术语：先等长档（主），无唯一解再退到变长档（兜底）。两档各自要求唯一。
     */
    private fun bestTermAt(text: String, start: Int): TermMatch? =
        bestEqualLenAt(text, start) ?: bestVarLenAt(text, start)

    /** 第一档：等长纯近音替换，「最长优先、同长替换最少、唯一」。 */
    private fun bestEqualLenAt(text: String, start: Int): TermMatch? {
        var best: String? = null
        var bestCost = Int.MAX_VALUE
        var ambiguous = false
        for (g in terms) {                       // terms 已按长度降序
            val len = g.length
            if (len < minFuzzyLen) break          // 降序，后续更短，直接停
            if (start + len > text.length) continue
            val cost = subCost(text, start, g) ?: continue
            when {
                best == null || len > best!!.length -> { best = g; bestCost = cost; ambiguous = false }
                len == best!!.length && cost < bestCost -> { bestCost = cost; best = g; ambiguous = false }
                len == best!!.length && cost == bestCost && g != best -> ambiguous = true
            }
        }
        // cost==0（已是标准术语）也返回 g（原样保留并推进），避免重复扫描；纠正发生在 cost>0。
        return if (best != null && !ambiguous) TermMatch(best!!, best!!.length) else null
    }

    /**
     * 第二档（变长兜底）：术语长度 ≥ [minVarLen]，原文窗口仅取 **len-1**
     * （ASR 漏识术语中的 1 字，需补回）。
     *
     * 刻意不用 len+1：否则会把「请/在/上/我」等句首虚词当成多余字删掉
     * （如「现在帮我打开时钟」→「现帮我打开时钟」）。
     */
    private fun bestVarLenAt(text: String, start: Int): TermMatch? {
        var best: String? = null
        var bestConsumed = 0
        var bestCost = Int.MAX_VALUE
        var ambiguous = false
        for (g in terms) {
            val len = g.length
            if (len < minVarLen) break            // 降序，后续更短，直接停
            val width = len - 1
            if (width < 1 || start + width > text.length) continue
            val cost = varCost(text, start, g, width) ?: continue
            when {
                best == null || len > best!!.length -> {
                    best = g; bestConsumed = width; bestCost = cost; ambiguous = false
                }
                len == best!!.length && cost < bestCost -> {
                    bestConsumed = width; bestCost = cost; best = g; ambiguous = false
                }
                len == best!!.length && cost == bestCost &&
                    (g != best || width != bestConsumed) -> ambiguous = true
            }
        }
        return if (best != null && !ambiguous) TermMatch(best!!, bestConsumed) else null
    }

    /** [text] 自 [start] 起与术语 [g] 等长纯近音替换的代价；不可达或超预算返回 null。 */
    private fun subCost(text: String, start: Int, g: String): Int? {
        val budget = maxSubsFor(g.length)
        var cost = 0
        for (k in g.indices) {
            val c = text[start + k]
            if (c == g[k]) continue
            if (!readingMap.allows(c, g[k])) return null
            cost++
            if (cost > budget) return null
        }
        return cost
    }

    /**
     * [text] 自 [start] 起、宽 [width] 的窗口与术语 [g] 的「近音替换 + 增删」编辑距离。
     * 替换仅当近音可达（[TermReadingMap.allows]），增删各计 1。整体须 ≤ 预算，否则返回 null。
     */
    private fun varCost(text: String, start: Int, g: String, width: Int): Int? {
        val budget = maxSubsFor(g.length)
        val m = g.length
        val inf = budget + 1
        // dp[j] = 对齐 raw 前 i 个字符与 g 前 j 个字符的最小编辑；逐行滚动。
        var prev = IntArray(m + 1) { it }
        for (i in 1..width) {
            val cur = IntArray(m + 1)
            cur[0] = i
            val rc = text[start + i - 1]
            for (j in 1..m) {
                val sub = when {
                    rc == g[j - 1] -> 0
                    readingMap.allows(rc, g[j - 1]) -> 1
                    else -> inf
                }
                cur[j] = minOf(
                    prev[j - 1] + sub, // 替换/同字
                    prev[j] + 1,       // 删 raw 一字
                    cur[j - 1] + 1,    // 插 g 一字
                ).coerceAtMost(inf)
            }
            prev = cur
        }
        val cost = prev[m]
        return if (cost in 1..budget) cost else null
    }

    private fun locateSpans(text: String): List<PoliceTermsSpan> {
        val spans = mutableListOf<PoliceTermsSpan>()
        var i = 0
        while (i < text.length) {
            val term = gazetteer.findLongestAt(text, i)
            if (term != null) {
                spans.add(
                    PoliceTermsSpan(
                        start = i,
                        end = i + term.length,
                        raw = term,
                        normalized = term,
                        valid = gazetteer.isKnown(term),
                    ),
                )
                i += term.length
            } else {
                i++
            }
        }
        return spans
    }
}
