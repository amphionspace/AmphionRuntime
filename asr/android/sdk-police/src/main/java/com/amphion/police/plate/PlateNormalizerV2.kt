package com.amphion.police.plate

import android.content.Context

/**
 * 车牌后处理 V2（面向全国车牌）。
 *
 * 设计（取代老方案 [PlateNormalizer] 的 28 个逐省手写函数），本质是一条线性链 WFST 解码：
 * 「输入格 ∘ 读音转换器 ∘ GA36 文法接受器 → 最短路」。
 * 1. 候选定位：从「省份简称 / 省份同音字」起点贪心收集有效字符（跳过分隔符）。
 * 2. 加权候选格：每个源字符经 [PlateReadingMap] 得到 1→N 带权候选（省份/字母/数字，权见
 *    [PlateReadingMap.substitutionCost]），有界笛卡尔展开即该格的显式实现。
 * 3. 文法接受器：用 [PlateValidatorV2] 按 GA36（普通 7 位 / 新能源 8 位）筛合法路径。
 * 4. 最短路 + 长度消歧：同一长度取「路径权最小」者；最长合法优先（8 位新能源优先于 7 位普通）。
 * 5. 锚词/上下文接受门（P4 降过纠）：纯恒等或低风险路径直接采纳；当路径依赖 ≥2 个「冒险替换」
 *    （字母/省份近音）且上下文无车牌锚词时，判为过纠并放弃（保留原文）。见 [acceptSpan]。
 *
 * 7/8 位歧义说明：新能源 8 位文法带能源标识 D/F（[PlateValidatorV2.isNewEnergySerial]），
 * 结构上不易与普通牌后接的普通字符巧合，故「凑满 8 位且合法新能源」时按最大匹配吃满 8 位，
 * 既能纠正「京AD一二三四五→京AD12345」类新能源牌，又不会吃掉车牌后真正的后续文字
 * （后续文字若无字母/数字读音候选，定位阶段就已在第 7 位前停止）。
 *
 * 仅做民用普通 + 新能源（本期范围）。与老方案完全独立，挂在 [PlateEnhancePrefs.plateV2Enabled] 开关后。
 */
class PlateNormalizerV2 private constructor(
    private val kb: PlateKnowledgeBase,
    private val readingMap: PlateReadingMap,
    private val validator: PlateValidatorV2,
    /**
     * 部署辖区省份提示（双重用途）：
     * 1. 丢省份兜底（P5-2）：ASR 偶尔完全丢掉省份简称（如「车牌号 H 28491」），纯文本无法凭空恢复，
     *    若提供本地辖区省份则在有锚词的「无省字母+序号」串前补省（仅当恰一个省份能使该串合法时）。
     * 2. 辖区先验 tie-break（P5-3c）：省份同音歧义平局时（如 及/即 → 吉 或 冀，等权等险），
     *    偏好辖区省份。仅在「同权同险」时生效，绝不覆盖更优路径，故已识别清楚的外地牌不受影响。
     * 默认空 = 全部关闭（不臆造、不偏置，零回归）。雄安部署建议置 ['冀','辽']。
     */
    private val contextProvinces: List<Char> = emptyList(),
) : AutoCloseable {

    private val homeProvinces: Set<Char> = contextProvinces.toSet()

    /** 候选车牌的省份（首字）是否属于部署辖区，用于平局偏好。 */
    private fun isHomeProvince(plate: String): Boolean =
        plate.isNotEmpty() && plate[0] in homeProvinces

    /** 候选格组合数上限，超过则退化为「逐位取首选」单候选，避免组合爆炸。 */
    private val maxCombos = 256

    /** 单个车牌最多消费的有效源字符数（普通 7 / 新能源 8，留余量到 9）。 */
    private val maxBodyChars = 9

    /** 无锚词时允许的「冒险替换」（字母/省份近音）上限；超过则判为过纠、放弃。 */
    private val maxRiskyUnanchored = 1

    /** 锚词扫描窗口：车牌前 [anchorPre] 字、车牌后 [anchorPost] 字（覆盖较短的查询整句）。 */
    private val anchorPre = 24
    private val anchorPost = 16

    /**
     * 车牌语境锚词：命中则放宽接受门，允许更冒险的纠正。
     * 警务车牌查询几乎必带「车/查/牌/号/辆」等词，故纳入这些高频语境字；
     * 真正的裸文本（无任何车牌语境）才会缺锚，从而拦住过纠。
     */
    private val anchors = listOf(
        "车", "查", "牌", "号", "辆", "报警", "登记", "记录", "驾", "肇事", "嫌疑", "套牌", "违",
    )

    fun normalize(text: String): PlateNormalizeResult {
        if (text.isEmpty()) return PlateNormalizeResult(text, emptyList())

        val spans = mutableListOf<PlateSpan>()
        var i = 0
        while (i < text.length) {
            if (!canStartHere(text[i])) {
                i++
                continue
            }
            val match = tryMatchPlateAt(text, i)
            if (match != null) {
                spans.add(match)
                i = match.end
            } else {
                i++
            }
        }

        if (contextProvinces.isNotEmpty()) appendContextProvinceSpans(text, spans)

        if (spans.isEmpty()) return PlateNormalizeResult(text, emptyList())

        val out = StringBuilder(text)
        for (span in spans.sortedByDescending { it.start }) {
            out.replace(span.start, span.end, span.normalized)
        }
        return PlateNormalizeResult(out.toString(), spans.sortedBy { it.start })
    }

    /**
     * 丢省份兜底（P5-2）：ASR 完全丢失省份简称时（如「车牌号 H 28491」），用部署地省份提示补省。
     * 仅在以下全部满足时触发，最大限度防止臆造：
     * 1. [contextProvinces] 非空（调用方显式提供本地辖区省份）；
     * 2. 该位置不是省份起点（省份在场的由主流程处理），且首个有效字符可作字母（机关位）；
     * 3. 上下文窗口内有车牌锚词；
     * 4. 候选省份中**恰有一个**能使该串合法（多个省份都合法则歧义，不补）。
     */
    private fun appendContextProvinceSpans(text: String, spans: MutableList<PlateSpan>) {
        val covered = BooleanArray(text.length)
        for (s in spans) for (k in s.start until s.end) if (k < text.length) covered[k] = true

        var i = 0
        while (i < text.length) {
            if (covered[i] || canStartHere(text[i]) ||
                readingMap.candidates(text[i]).none { it in PlateKnowledgeBase.PLATE_ALPHABET }
            ) {
                i++
                continue
            }
            val (body, bodyIdx) = collectSig(text, i)
            // 机关位(1) + 序号(5或6) = 6 或 7 个有效字符
            val match = inferWithContextProvince(text, i, body, bodyIdx)
            if (match != null) {
                spans.add(PlateSpan(i, match.endSource, text.substring(i, match.endSource), match.plate, valid = true))
                i = match.endSource
            } else {
                i++
            }
        }
    }

    private fun inferWithContextProvince(
        text: String,
        start: Int,
        body: List<Char>,
        bodyIdx: List<Int>,
    ): Match? {
        for (plateLen in intArrayOf(8, 7)) {
            val bodyLen = plateLen - 1
            if (body.size < bodyLen) continue
            val end = bodyIdx[bodyLen - 1] + 1
            if (!hasAnchor(text, start, end)) continue
            val bodySeq = body.subList(0, bodyLen)
            val hits = contextProvinces.mapNotNull { p ->
                bestCandidateForLength(listOf(p) + bodySeq, plateLen)
            }
            // 恰有一个省份合法才补；多个合法 = 歧义，放弃
            if (hits.size == 1) return Match(hits[0].plate, end, plateLen)
        }
        return null
    }

    /** 起点须能解析出省份（直接是省份简称，或读音候选里含省份）。 */
    private fun canStartHere(c: Char): Boolean =
        readingMap.candidates(c).any { kb.isProvinceChar(it) }

    /** 从 [start] 起收集有效源字符（跳过分隔符，遇无候选字符即停），返回 (字符, 原文下标)。 */
    private fun collectSig(text: String, start: Int): Pair<List<Char>, List<Int>> {
        val sigChars = mutableListOf<Char>()
        val sigIndex = mutableListOf<Int>()
        var j = start
        while (j < text.length && sigChars.size < maxBodyChars) {
            val c = text[j]
            if (isSeparator(c)) {
                j++
                continue
            }
            if (readingMap.candidates(c).isEmpty()) break
            sigChars.add(c)
            sigIndex.add(j)
            j++
        }
        return sigChars to sigIndex
    }

    private fun tryMatchPlateAt(text: String, start: Int): PlateSpan? {
        val (sigChars, sigIndex) = collectSig(text, start)
        if (sigChars.size < 7) return null

        // 变体 A：原始有效字符序列。
        val matchA = bestAcceptedMatch(text, start, sigChars) { len -> sigIndex[len - 1] + 1 }

        // 变体 B：相邻同字折叠（P5-2 重复字符折叠，如「黑KK41258」→「黑K41258」）。
        // 仅合并“相邻且完全相同”的源字符，故不会误伤真实双字母牌（如 青AA88P0 本就是完整 7 位，
        // 无需折叠即被变体 A 以更大覆盖采纳）。
        val (dChars, dEnd, dCover) = dedupAdjacent(sigChars, sigIndex)
        val matchB = if (dChars.size != sigChars.size) {
            bestAcceptedMatch(text, start, dChars, coverageForLen = { len -> dCover[len - 1] }) { len ->
                dEnd[len - 1]
            }
        } else {
            null
        }

        // 覆盖更多原始口述字符者优先（折叠把被吃掉的尾字也纳入车牌）；覆盖相同则取原始（改动更少）。
        val chosen = when {
            matchB != null && (matchA == null || matchB.coverage > matchA.coverage) -> matchB
            else -> matchA
        } ?: return null

        val raw = text.substring(start, chosen.endSource)
        return PlateSpan(start, chosen.endSource, raw, chosen.plate, valid = true)
    }

    private data class Match(val plate: String, val endSource: Int, val coverage: Int)

    /**
     * 对给定有效字符序列做「最大匹配 + 接受门」解码：先试 8 位（新能源）再 7 位（普通），
     * 返回首个通过接受门的合法车牌；无则 null。
     *
     * @param endForLen 长度 len 对应在原文中的结束下标（不含）
     * @param coverageForLen 长度 len 实际覆盖的原始有效字符数（折叠时 > len）
     */
    private fun bestAcceptedMatch(
        text: String,
        start: Int,
        seq: List<Char>,
        coverageForLen: (Int) -> Int = { it },
        endForLen: (Int) -> Int,
    ): Match? {
        for (len in intArrayOf(8, 7)) {
            if (seq.size < len) continue
            val cand = bestCandidateForLength(seq, len) ?: continue
            val end = endForLen(len)
            if (!acceptSpan(text, start, end, cand)) continue
            return Match(cand.plate, end, coverageForLen(len))
        }
        return null
    }

    /**
     * 折叠相邻完全相同的源字符，返回 (折叠后序列, 各折叠位的原文结束下标, 各折叠位累计覆盖的原始字符数)。
     */
    private fun dedupAdjacent(
        sigChars: List<Char>,
        sigIndex: List<Int>,
    ): Triple<List<Char>, IntArray, IntArray> {
        val chars = ArrayList<Char>(sigChars.size)
        val ends = ArrayList<Int>(sigChars.size)
        val cover = ArrayList<Int>(sigChars.size)
        var i = 0
        while (i < sigChars.size) {
            val c = sigChars[i]
            var j = i
            while (j + 1 < sigChars.size && sigChars[j + 1] == c) j++
            chars.add(c)
            ends.add(sigIndex[j] + 1)
            cover.add(j + 1)
            i = j + 1
        }
        return Triple(chars, ends.toIntArray(), cover.toIntArray())
    }

    /**
     * 锚词/上下文接受门（P4）：决定一个合法候选是否真正落地，用于压制边缘过纠。
     * - 纯恒等（[Candidate.cost]==0，即已是规范车牌，仅做大小写/全角归一）→ 直接采纳。
     * - 冒险替换数 ≤ [maxRiskyUnanchored] → 采纳（如单个省份近音或单个字母近音，仍属高置信）。
     * - 否则要求上下文窗口内出现车牌锚词；无锚词则判为过纠、放弃。
     */
    private fun acceptSpan(text: String, start: Int, end: Int, cand: Candidate): Boolean {
        if (cand.cost == 0) return true
        if (cand.risky <= maxRiskyUnanchored) return true
        return hasAnchor(text, start, end)
    }

    /** 车牌前 [anchorPre] 字、后 [anchorPost] 字窗口内是否出现 [anchors]。 */
    private fun hasAnchor(text: String, start: Int, end: Int): Boolean {
        val before = text.substring((start - anchorPre).coerceAtLeast(0), start)
        val after = text.substring(end, (end + anchorPost).coerceAtMost(text.length))
        val ctx = before + after
        return anchors.any { ctx.contains(it) }
    }

    /** 对前 [len] 个有效源字符做候选格枚举，返回该长度下的最优合法候选；无则 null。 */
    private fun bestCandidateForLength(sigChars: List<Char>, len: Int): Candidate? {
        // 逐位候选集合：位 0 仅省份；位 ≥1 仅字母/数字。
        val perPos = ArrayList<List<Char>>(len)
        var combos = 1L
        for (pos in 0 until len) {
            val raw = readingMap.candidates(sigChars[pos])
            val filtered = if (pos == 0) {
                raw.filter { kb.isProvinceChar(it) }
            } else {
                raw.filter { it in PlateKnowledgeBase.PLATE_ALPHABET || it.isDigit() }
            }
            if (filtered.isEmpty()) return null
            perPos.add(filtered)
            combos *= filtered.size
        }

        val sequences: List<CharArray> = if (combos in 1..maxCombos.toLong()) {
            expandCartesian(perPos)
        } else {
            // 退化：逐位取首选（优先与原字符一致的选项），只产生一条序列。
            listOf(CharArray(len) { pos -> preferIdentity(perPos[pos], sigChars[pos]) })
        }

        var best: Candidate? = null
        for (seq in sequences) {
            val plate = String(seq)
            if (!validator.isValidPlate(plate)) continue
            var cost = 0
            var risky = 0
            for (pos in 0 until len) {
                val w = readingMap.substitutionCost(sigChars[pos], seq[pos])
                cost += w
                if (w >= PlateReadingMap.COST_LETTER) {
                    // 结构规则（P5-3c）：位 0 落在部署辖区省份的替换属高置信先验，不计入「冒险预算」。
                    // 这样「继而→冀R」这类省份被识别成两段（继=冀 + 而=R）的结构性误识，
                    // 只剩 而→R 一个冒险替换，可在无锚词时通过接受门。辖区为空时此项不生效。
                    val homePrior = pos == 0 && seq[pos] in homeProvinces
                    if (!homePrior) risky++
                }
            }
            val cur = best
            // 最短路 + 辖区先验：先比路径权，再比冒险替换数；仍相等时，偏好部署辖区省份
            // （[contextProvinces]）。tie-break 只在「同权同险」时生效，绝不覆盖更优路径，
            // 故已识别清楚的外地牌（identity，cost 0）不受影响。
            val better = when {
                cur == null -> true
                cost != cur.cost -> cost < cur.cost
                risky != cur.risky -> risky < cur.risky
                else -> isHomeProvince(plate) && !isHomeProvince(cur.plate)
            }
            if (better) {
                best = Candidate(plate = plate, length = len, cost = cost, risky = risky)
            }
        }
        return best
    }

    private fun preferIdentity(options: List<Char>, original: Char): Char {
        val up = original.uppercaseChar()
        return options.firstOrNull { it == up || it == original } ?: options.first()
    }

    private fun expandCartesian(perPos: List<List<Char>>): List<CharArray> {
        var acc = listOf(CharArray(0))
        for (options in perPos) {
            val next = ArrayList<CharArray>(acc.size * options.size)
            for (prefix in acc) {
                for (opt in options) {
                    val arr = prefix.copyOf(prefix.size + 1)
                    arr[prefix.size] = opt
                    next.add(arr)
                }
            }
            acc = next
        }
        return acc
    }

    private fun isSeparator(c: Char): Boolean =
        c.isWhitespace() || c == '·' || c == '.' || c == '-' || c == '—' || c in "。，；！？．、"

    override fun close() { /* V2 暂无 native 资源 */ }

    /**
     * 一条合法解码路径。
     * @property cost 路径总权（[PlateReadingMap.substitutionCost] 之和；0 表示纯恒等）
     * @property risky 冒险替换（字母/省份近音）位数，供接受门判断
     */
    private data class Candidate(
        val plate: String,
        val length: Int,
        val cost: Int,
        val risky: Int,
    )

    companion object {
        fun create(
            context: Context,
            contextProvinces: List<Char> = emptyList(),
        ): PlateNormalizerV2 {
            val kb = PlateKnowledgeBase.load(context)
            val readingMap = PlateReadingMap.load(context, kb)
            return PlateNormalizerV2(kb, readingMap, PlateValidatorV2(kb), contextProvinces)
        }

        internal fun create(
            kb: PlateKnowledgeBase,
            readingMap: PlateReadingMap,
            contextProvinces: List<Char> = emptyList(),
        ): PlateNormalizerV2 =
            PlateNormalizerV2(kb, readingMap, PlateValidatorV2(kb), contextProvinces)
    }
}
