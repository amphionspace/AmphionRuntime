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
 *   再以 [PoliceStationGazetteer]（闭集标准名单）当**校验器**，先应用完整站名别名，
 *   再选编辑代价最小且**唯一**的合法站名（等价于车牌 V2 的最短路 + 文法接受 + 消歧）。
 *
 * 这样无需逐条枚举听错写法：只要听到的片段距某个真实站名 ≤ [maxEdits] 个编辑且唯一，即纠正；
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

    /** 最多容忍两个字级编辑；超过判为不可信、保留原文。 */
    private val maxEdits = 2

    companion object {
        private const val GAZETTEER_ASSET = "police_station/station_gazetteer.txt"
        private val STATION_SUFFIX = Regex("""[\u4e00-\u9fff0-9]{2,28}派出所""")
        private val COMMAND_PREFIXES = listOf(
            "麻烦汇总一下", "帮忙汇总一下", "麻烦统计一下", "帮忙统计一下",
            "麻烦整理一下", "帮忙整理一下", "麻烦导出一下", "帮忙导出一下",
            "麻烦核对一下", "麻烦核实一下", "麻烦核查一下", "麻烦核一下",
            "帮忙查一下", "帮我查一下", "麻烦查一下", "帮忙看看", "帮我看一下",
            "给我看一下", "给我拉一下", "整理一下", "汇总一下", "统计一下",
            "导出一下", "麻烦汇总", "帮忙汇总", "麻烦统计", "帮忙统计",
            "麻烦整理", "帮忙整理", "麻烦导出", "帮忙导出", "麻烦核",
            "麻烦看一下", "麻烦看下", "请帮忙整理一下", "请帮忙", "请把",
            "看看", "看一下", "看下", "查一下", "给我", "把", "请",
            "汇总", "统计", "导出", "整理", "对比", "核对", "核实", "核查",
        ).sortedByDescending { it.length }

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
     * [STATION_SUFFIX] 可能吞掉句首指令词，因此只剥离固定指令前缀；不再允许 DP 任意跳过
     * raw 前缀。完整站名别名优先，模糊层只接受总代价不超过 [maxEdits] 的唯一最近候选。
     */
    private fun normalizeSpanV2(raw: String, context: String): String {
        if (gazetteer.isKnown(raw)) return raw

        // 已知完整站名误识优先，命中结果仍须通过闭集 gazetteer 校验。
        val aliased = homophones.applyGazetteerConstrained(raw, gazetteer)
        if (gazetteer.isKnown(aliased)) return aliased

        val stationLike = stripCommandPrefix(raw)
        if (gazetteer.isKnown(stationLike)) return stationLike

        // 等长时只允许读音表批准的替换；变长档仅处理真实长度差。这样任意不同字
        // 不能通过“删 1 + 插 1”绕过近音白名单。
        matchTier { g -> substitutionCost(stationLike, g) }?.let { return it }
        matchTier { g -> editCost(stationLike, g) }?.let { return it }

        gazetteer.findLongestIn(raw)?.let { return it }
        gazetteer.findLongestIn(context)?.let { return it }
        return raw
    }

    /** 在完整 gazetteer 上选择全局代价最小且唯一的标准站名；并列或无解返回 null。 */
    private inline fun matchTier(cost: (String) -> Int?): String? {
        var best: String? = null
        var bestCost = Int.MAX_VALUE
        var ambiguous = false
        for (g in names) {
            val c = cost(g) ?: continue
            when {
                c < bestCost -> { best = g; bestCost = c; ambiguous = false }
                c == bestCost && g != best -> ambiguous = true
            }
        }
        return if (best != null && !ambiguous) best else null
    }

    private fun stripCommandPrefix(raw: String): String {
        var out = raw
        var changed: Boolean
        do {
            changed = false
            for (prefix in COMMAND_PREFIXES) {
                if (out.startsWith(prefix) && out.length > prefix.length) {
                    out = out.removePrefix(prefix)
                    changed = true
                    break
                }
            }
        } while (changed)
        return out
    }

    /** 等长纯替换，非近音不可达。 */
    private fun substitutionCost(raw: String, g: String): Int? {
        if (raw.length != g.length) return null
        var cost = 0
        for (i in g.indices) {
            if (raw[i] == g[i]) continue
            if (!readingMap.allows(raw[i], g[i])) return null
            cost++
            if (cost > maxEdits) return null
        }
        return cost
    }

    /**
     * 完整站名编辑距离 DP：
     * - 替换：相等 0；近音（[StationReadingMap]）1；否则不可达。
     * - 增/删字：各计 1；不允许免费跳过任意前缀。
     * 总代价 ≤ [maxEdits] 才返回，否则 null。
     */
    private fun editCost(raw: String, g: String): Int? {
        if (raw.length == g.length) return null
        if (kotlin.math.abs(raw.length - g.length) > maxEdits) return null
        val n = raw.length
        val m = g.length
        val inf = maxEdits + 1
        var prev = IntArray(m + 1) { it }        // i=0：插入 g 前 j 字
        for (i in 1..n) {
            val cur = IntArray(m + 1)
            cur[0] = i
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
        return if (cost <= maxEdits) cost else null
    }
}
