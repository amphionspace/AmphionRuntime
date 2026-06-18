package com.amphion.police.terms

import android.content.Context
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * 警务术语 V2 专用：**字级**近音候选表（与派出所 [com.amphion.police.station.StationReadingMap] 同思路）。
 *
 * 从同一份 `term_homophones.csv` 拆出等长短语的逐位近音对（`from[i]→to[i]`，不等处，cost=1），
 * 供 [PoliceTermsNormalizerV2] 在 gazetteer（标准术语表）上做「近音重组 + 校验」。
 *
 * 仅 V2 引用；V1（[PoliceTermsHomophoneDict]）完全不读此结构，互不影响、可随时切回。
 */
internal class TermReadingMap private constructor(
    private val subs: Map<Char, Set<Char>>,
) {
    fun allows(from: Char, to: Char): Boolean =
        from == to || subs[from]?.contains(to) == true

    companion object {
        private const val ASSET_PATH = "police_terms/term_homophones.csv"

        fun load(context: Context): TermReadingMap {
            context.assets.open(ASSET_PATH).use { input ->
                return loadFromReader(BufferedReader(InputStreamReader(input, Charsets.UTF_8)))
            }
        }

        fun loadFromReader(reader: BufferedReader): TermReadingMap {
            val subs = linkedMapOf<Char, MutableSet<Char>>()
            reader.forEachLine { line ->
                val s = line.trim()
                if (s.isEmpty() || s.startsWith("#")) return@forEachLine
                val parts = s.split(",")
                if (parts.size < 2) return@forEachLine
                val from = parts[0].trim()
                val to = parts[1].trim()
                if (from.isEmpty() || from.length != to.length) return@forEachLine
                for (i in from.indices) {
                    if (from[i] != to[i]) subs.getOrPut(from[i]) { linkedSetOf() }.add(to[i])
                }
            }
            return TermReadingMap(subs.mapValues { it.value.toSet() })
        }
    }
}
