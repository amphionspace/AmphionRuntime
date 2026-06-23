package com.amphion.police.station

import android.content.Context
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * 派出所 V2 专用：**字级**谐音候选表（与车牌 [com.amphion.police.plate.PlateReadingMap] 同思路）。
 *
 * 老方案（V1）把 `station_homophones.csv` 当成「整词短语」逐条整句替换，位置/词形写死，
 * 新的听错组合必须再人肉补一条。本表改为从同一份 CSV **拆出字级近音对**：
 * 凡 `from,to` 等长，则逐位提取 `from[i]→to[i]`（不等处）作为一条字级近音 (cost=1)。
 *
 * 这样「父→夫」「阜→府」「珠→渚」等近音一旦学到，可在 **任意** 站名里复用、自由重组，
 * 再由 [PoliceStationGazetteer]（闭集名单）当「校验器」筛出唯一合法站名（见 V2 归一逻辑）。
 *
 * 仅 V2 引用；V1（[PoliceStationHomophoneDict]）完全不读此结构，互不影响、可随时切回。
 */
internal class StationReadingMap private constructor(
    private val subs: Map<Char, Set<Char>>,
) {
    /** 源字符 [from] 是否能近音替换成 [to]（含恒等）。 */
    fun allows(from: Char, to: Char): Boolean =
        from == to || subs[from]?.contains(to) == true

    companion object {
        private const val ASSET_PATH = "police_station/station_homophones.csv"

        fun load(context: Context): StationReadingMap {
            context.assets.open(ASSET_PATH).use { input ->
                return loadFromReader(BufferedReader(InputStreamReader(input, Charsets.UTF_8)))
            }
        }

        fun loadFromReader(reader: BufferedReader): StationReadingMap {
            val subs = linkedMapOf<Char, MutableSet<Char>>()
            reader.forEachLine { line ->
                val s = line.trim()
                if (s.isEmpty() || s.startsWith("#")) return@forEachLine
                val parts = s.split(",")
                if (parts.size < 2) return@forEachLine
                val from = parts[0].trim()
                val to = parts[1].trim()
                // 仅从「等长」短语拆字级近音；变长（增删字/标点）不在字级模型内。
                if (from.isEmpty() || from.length != to.length) return@forEachLine
                for (i in from.indices) {
                    if (from[i] != to[i]) {
                        subs.getOrPut(from[i]) { linkedSetOf() }.add(to[i])
                    }
                }
            }
            return StationReadingMap(subs.mapValues { it.value.toSet() })
        }
    }
}
