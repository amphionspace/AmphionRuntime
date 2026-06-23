package com.amphion.police.station

import android.content.Context
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * 派出所后处理 **V2**（与车牌 [com.amphion.police.plate.PlateNormalizerV2] 同骨架）。
 *
 * 与 V1（[PoliceStationNormalizer]）的唯一区别在「站名片段归一」这一步：
 * - V1：把 gazetteer 类谐音对当整词短语，最多 4 轮贪心整句替换，命中标准表才落地。
 * - V2：把片段当**字级候选格**——每个字经 [StationReadingMap] 得到近音候选，
 *   再以 [PoliceStationGazetteer]（闭集标准名单）当**校验器**，在「同长度的合法站名」里
 *   选「字级近音替换数最少」且**唯一**的那个（等价于车牌 V2 的最短路 + 文法接受 + 消歧）。
 *
 * 这样无需逐条枚举听错写法：只要听到的片段距某个真实站名 ≤ [maxSubs] 个近音替换且唯一，即纠正；
 * 模棱两可（多个站名等距）则保留原文，避免臆造。
 *
 * 外层（解码守卫、全局谐音、标点、定位、整句润色）复用 V1 同款工具，保证仅对比「片段归一」差异。
 * V1 文件完全未改，可随时切回。
 */
class PoliceStationNormalizerV2 private constructor(
    private val homophones: PoliceStationHomophoneDict,
    private val gazetteer: PoliceStationGazetteer,
    private val names: List<String>,
    private val readingMap: StationReadingMap,
) {

    /** 站名片段允许的最大字级近音替换数；超过判为不可信、保留原文。 */
    private val maxSubs = 4

    companion object {
        private const val GAZETTEER_ASSET = "police_station/station_gazetteer.txt"
        private val STATION_SUFFIX = Regex("""[\u4e00-\u9fff0-9]{2,28}派出所""")

        fun create(context: Context): PoliceStationNormalizerV2 {
            val names = context.assets.open(GAZETTEER_ASSET).use { input ->
                BufferedReader(InputStreamReader(input, Charsets.UTF_8)).readLines()
                    .map { it.trim() }
                    .filter { it.isNotEmpty() && !it.startsWith("#") }
                    .distinct()
                    .sortedByDescending { it.length }
            }
            return PoliceStationNormalizerV2(
                PoliceStationHomophoneDict.load(context),
                PoliceStationGazetteer.load(context),
                names,
                StationReadingMap.load(context),
            )
        }

        internal fun create(
            homophones: PoliceStationHomophoneDict,
            gazetteer: PoliceStationGazetteer,
            names: List<String>,
            readingMap: StationReadingMap,
        ): PoliceStationNormalizerV2 =
            PoliceStationNormalizerV2(homophones, gazetteer, names, readingMap)
    }

    fun normalize(text: String): PoliceStationNormalizeResult {
        if (text.isEmpty()) {
            return PoliceStationNormalizeResult(text, emptyList(), decodeCollapse = true)
        }
        if (PoliceStationDecodeGuard.isDecodeCollapse(text)) {
            return PoliceStationNormalizeResult(text, emptyList(), decodeCollapse = true)
        }

        var corrected = homophones.applyGlobalPhrases(text)
        corrected = PoliceStationPunctUtil.normalizeAdminPunct(corrected)

        val span = locateSpan(corrected)
            ?: return finish(PoliceStationSentenceUtil.polish(corrected), emptyList())

        var normalizedName = normalizeSpanV2(span.raw, corrected)
        normalizedName = PoliceStationPunctUtil.normalizeAdminPunct(normalizedName)
        val valid = gazetteer.isKnown(normalizedName)
        var outText = corrected.replaceRange(span.start, span.end, normalizedName)
        outText = PoliceStationSentenceUtil.polish(outText)

        return finish(
            outText,
            listOf(
                PoliceStationSpan(
                    start = span.start,
                    end = span.end,
                    raw = span.raw,
                    normalized = normalizedName,
                    valid = valid,
                ),
            ),
        )
    }

    private fun finish(text: String, spans: List<PoliceStationSpan>): PoliceStationNormalizeResult =
        PoliceStationNormalizeResult(text, spans, decodeCollapse = false)

    private data class RawSpan(val start: Int, val end: Int, val raw: String)

    private fun locateSpan(text: String): RawSpan? {
        gazetteer.findLongestIn(text)?.let { known ->
            val start = text.indexOf(known)
            if (start >= 0) return RawSpan(start, start + known.length, known)
        }
        val m = STATION_SUFFIX.findAll(text).toList()
        if (m.isEmpty()) return null
        val best = m.minByOrNull { it.value.length } ?: return null
        return RawSpan(best.range.first, best.range.last + 1, best.value)
    }

    /**
     * V2 片段归一：字级候选格 ∩ gazetteer 校验器 → 最少近音替换且唯一者。
     *
     * 因 [STATION_SUFFIX] 会贪心吞掉「派出所」前的整段口语（如「帮我统计一下…金阳派出所」），
     * 故把每个标准站名**对齐到「派出所」词尾**（比对 raw 末 g.length 个字），允许前缀有多余口语字。
     * 优先最长站名（语义最完整，等价 V1 的 findLongestIn）；同长再取近音替换最少；仍并列则判歧义、不纠。
     */
    private fun normalizeSpanV2(raw: String, context: String): String {
        if (gazetteer.isKnown(raw)) return raw

        // 一档（主）：等长纯近音替换——最稳，覆盖绝大多数同音误识，对已调优集合零回退。
        matchTier(raw) { g -> if (g.length > raw.length) null else tailSubCost(raw, g) }?.let { return it }
        // 二档（兜底）：仅当等长无解时，用编辑距离处理「增/删字」变长误识；唯一才纠，否则保留。
        matchTier(raw) { g -> fuzzyTailCost(raw, g) }?.let { return it }

        gazetteer.findLongestIn(raw)?.let { return it }
        gazetteer.findLongestIn(context)?.let { return it }
        return raw
    }

    /** 在 gazetteer 上按 [cost] 选「最长优先、同长代价最小、唯一」的标准站名；并列或无解返回 null。 */
    private inline fun matchTier(raw: String, cost: (String) -> Int?): String? {
        var best: String? = null
        var bestCost = Int.MAX_VALUE
        var ambiguous = false
        for (g in names) {                       // names 已按长度降序
            val c = cost(g) ?: continue
            when {
                best == null || g.length > best!!.length -> { best = g; bestCost = c; ambiguous = false }
                g.length == best!!.length && c < bestCost -> { bestCost = c; best = g; ambiguous = false }
                g.length == best!!.length && c == bestCost && g != best -> ambiguous = true
            }
        }
        return if (best != null && !ambiguous) best else null
    }

    /** 把站名 [g] 对齐到 [raw] 词尾做等长纯替换，返回近音替换数；不可达或超 [maxSubs] 返回 null。 */
    private fun tailSubCost(raw: String, g: String): Int? {
        val offset = raw.length - g.length
        var cost = 0
        for (i in g.indices) {
            val r = raw[offset + i]
            if (r == g[i]) continue
            if (!readingMap.allows(r, g[i])) return null
            cost++
            if (cost > maxSubs) return null
        }
        return cost
    }

    /**
     * 把站名 [g] 模糊对齐到 [raw] 词尾（编辑距离 DP）：
     * - 替换：相等 0；近音（[StationReadingMap]）1；否则不可达。
     * - 增/删字：各计 1（覆盖「集美→集美区」漏字、「三一巴克→沙依巴克」等变长误识）。
     * - 前缀自由跳过（[STATION_SUFFIX] 会吞掉「派出所」前的整段口语），匹配须消费完整 [g] 且止于 raw 末。
     * 总代价 ≤ [maxSubs] 才返回，否则 null。
     */
    private fun fuzzyTailCost(raw: String, g: String): Int? {
        val n = raw.length
        val m = g.length
        val inf = maxSubs + 1
        var prev = IntArray(m + 1) { it }        // i=0：插入 g 前 j 字
        for (i in 1..n) {
            val cur = IntArray(m + 1)
            cur[0] = 0                           // 前缀自由跳过：可在任意位置起配
            for (j in 1..m) {
                val sub = when {
                    raw[i - 1] == g[j - 1] -> 0
                    readingMap.allows(raw[i - 1], g[j - 1]) -> 1
                    else -> inf
                }
                cur[j] = minOf(
                    prev[j - 1] + sub,           // 替换/相等
                    prev[j] + 1,                 // 删 raw[i-1]（raw 多字）
                    cur[j - 1] + 1,              // 插 g[j-1]（raw 漏字）
                ).coerceAtMost(inf)
            }
            prev = cur
        }
        val cost = prev[m]
        return if (cost <= maxSubs) cost else null
    }
}
