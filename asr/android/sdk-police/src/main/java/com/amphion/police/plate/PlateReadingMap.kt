package com.amphion.police.plate

import android.content.Context
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * Layer 1：读音映射（PlateNormalizer V2 用）。
 *
 * 把 `plate/plate_homophones.csv`（`from,to,category`）按 `from` 分组为 **1→N** 候选，
 * 即一个源字符可对应多个候选目标（省份简称 / 字母 / 数字）。CSV 中本就有 `优→V`、`优→U`
 * 这类多映射，分组后天然成为候选集合，用于 V2 的候选格枚举。
 *
 * 再并入 [PlateKnowledgeBase] 的省份同音字（确保省别覆盖），以及「省份/字母/数字」自身的恒等映射。
 *
 * 与老方案的 [PlateHomophoneDict]（1→1，last-wins）相互独立，互不影响。
 */
class PlateReadingMap private constructor(
    private val map: Map<Char, Set<Char>>,
    private val costs: Map<Char, Map<Char, Int>>,
) {

    /**
     * 源字符 [c] 的候选目标集合（含其自身的恒等映射）。
     * 返回的每个目标要么是省份简称、要么是车牌字母（A–Z 去 I/O）、要么是数字。
     */
    fun candidates(c: Char): Set<Char> {
        val upper = c.uppercaseChar()
        val base = map[c] ?: map[upper]
        val out = linkedSetOf<Char>()
        if (base != null) out.addAll(base)
        // 恒等：已是车牌字母 / 数字时映射到自身
        if (upper in PlateKnowledgeBase.PLATE_ALPHABET) out.add(upper)
        if (c.isDigit()) out.add(c)
        return out
    }

    /**
     * 替换代价（WFST 边权，热带半环最短路用）。值越大表示该读音越「冒险」：
     * - 0：恒等（源字符本就是目标省份/字母/数字）
     * - [COST_DIGIT]：中文数字 / 数字近音 → 数字（如 一→1，最稳）
     * - [COST_LETTER]：字母近音 → 字母（如 优→U，存在歧义）
     * - [COST_PROVINCE]：省份近音 → 省份简称（如 济→冀，最易过纠）
     *
     * 用于 [PlateNormalizerV2] 的路径打分与「冒险替换」计数（[isRisky]）。
     */
    fun substitutionCost(from: Char, to: Char): Int {
        val upper = from.uppercaseChar()
        if (to == from || to == upper) return 0
        costs[from]?.get(to)?.let { return it }
        costs[upper]?.get(to)?.let { return it }
        return COST_DEFAULT
    }

    /** 是否为「冒险替换」（字母/省份近音，非恒等、非数字）。 */
    fun isRisky(from: Char, to: Char): Boolean = substitutionCost(from, to) >= COST_LETTER

    companion object {

        const val COST_DIGIT = 1
        const val COST_LETTER = 2
        const val COST_PROVINCE = 3
        private const val COST_DEFAULT = COST_LETTER

        /** 复用老方案的谐音表资产（只读，不修改）。 */
        const val ASSET_PATH = "plate/plate_homophones.csv"

        /** V2 专用读音补充表（老方案不读；真机语料挖掘所得，与 [ASSET_PATH] 合并）。 */
        const val SUPPLEMENT_ASSET_PATH = "plate/plate_readings_v2.csv"

        fun load(context: Context, kb: PlateKnowledgeBase): PlateReadingMap {
            val base = context.assets.open(ASSET_PATH)
                .use { BufferedReader(InputStreamReader(it, Charsets.UTF_8)).readLines() }
            val supplement = runCatching {
                context.assets.open(SUPPLEMENT_ASSET_PATH)
                    .use { BufferedReader(InputStreamReader(it, Charsets.UTF_8)).readLines() }
            }.getOrDefault(emptyList())
            return loadFromLines(base + supplement, kb)
        }

        /** 单文件加载（兼容旧调用）；多文件请用 [loadFromReaders]。 */
        fun loadFromReader(reader: BufferedReader, kb: PlateKnowledgeBase): PlateReadingMap =
            loadFromReaders(listOf(reader), kb)

        /** 合并多个读音表（如 base 谐音表 + V2 补充表）。 */
        fun loadFromReaders(
            readers: List<BufferedReader>,
            kb: PlateKnowledgeBase,
        ): PlateReadingMap = loadFromLines(readers.flatMap { it.readLines() }, kb)

        private fun loadFromLines(lines: List<String>, kb: PlateKnowledgeBase): PlateReadingMap {
            val grouped = linkedMapOf<Char, MutableSet<Char>>()
            val costs = linkedMapOf<Char, MutableMap<Char, Int>>()
            // V2 专属：压制 base 谐音表里的噪声候选（如 优→V、扣→K，真机一律应为 U/Q）。
            // 仅作用于 PlateReadingMap（V2），V1 的 PlateHomophoneDict 不读此结构，互不影响。
            val suppress = linkedSetOf<Pair<Char, Char>>()

            fun record(from: Char, to: Char, cost: Int) {
                grouped.getOrPut(from) { linkedSetOf() }.add(to)
                val row = costs.getOrPut(from) { linkedMapOf() }
                val prev = row[to]
                if (prev == null || cost < prev) row[to] = cost
            }

            for (line in lines) {
                val s = line.trim()
                if (s.isEmpty() || s.startsWith("#")) continue
                val parts = s.split(",")
                if (parts.size < 2) continue
                val from = parts[0].trim()
                val to = parts[1].trim()
                if (from.length != 1 || to.length != 1) continue
                val category = parts.getOrNull(2)?.trim().orEmpty()
                if (category == "suppress") {
                    suppress.add(from[0] to to[0])
                    continue
                }
                val cost = if (from[0] == to[0]) {
                    0
                } else when (category) {
                    "digit" -> COST_DIGIT
                    "letter" -> COST_LETTER
                    "province" -> COST_PROVINCE
                    else -> COST_DEFAULT
                }
                record(from[0], to[0], cost)
            }
            // 并入知识库省份同音字 + 省份简称自身（省份近音代价 = COST_PROVINCE）
            for (ch in kb.provinceChars) {
                val spec = kb.province(ch) ?: continue
                record(ch, ch, 0)
                for (h in spec.homophones) {
                    record(h, ch, if (h == ch) 0 else COST_PROVINCE)
                }
            }
            // 应用压制（最后执行，确保覆盖 base + 补充 + 知识库的所有来源）。
            for ((from, to) in suppress) {
                grouped[from]?.remove(to)
                costs[from]?.remove(to)
            }
            return PlateReadingMap(
                grouped.mapValues { it.value.toSet() },
                costs.mapValues { it.value.toMap() },
            )
        }
    }
}
