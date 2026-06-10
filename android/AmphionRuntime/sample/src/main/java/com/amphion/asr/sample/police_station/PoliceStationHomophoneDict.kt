package com.amphion.asr.sample.police_station

import android.content.Context
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * 派出所场景谐音/误识映射：from,to,category。
 * - global（含 term/punct/place/district）：整句无条件替换
 * - gazetteer：仅在校正站名片段时，且替换结果命中 gazetteer 才生效
 */
internal class PoliceStationHomophoneDict(
    private val globalPhrases: List<Pair<String, String>>,
    private val gazetteerPhrases: List<Pair<String, String>>,
) {
    companion object {
        private const val ASSET_PATH = "police_station/station_homophones.csv"

        fun load(context: Context): PoliceStationHomophoneDict {
            context.assets.open(ASSET_PATH).use { input ->
                return loadFromReader(BufferedReader(InputStreamReader(input, Charsets.UTF_8)))
            }
        }

        fun loadFromReader(reader: BufferedReader): PoliceStationHomophoneDict {
            val global = mutableListOf<Pair<String, String>>()
            val gazetteer = mutableListOf<Pair<String, String>>()
            reader.forEachLine { line ->
                val s = line.trim()
                if (s.isEmpty() || s.startsWith("#")) return@forEachLine
                val parts = s.split(",")
                if (parts.size < 2) return@forEachLine
                val from = parts[0].trim()
                val to = parts[1].trim()
                if (from.isEmpty() || to.isEmpty()) return@forEachLine
                val category = parts.getOrNull(2)?.trim()?.lowercase().orEmpty()
                val pair = from to to
                if (category == "gazetteer") {
                    gazetteer += pair
                } else {
                    global += pair
                }
            }
            global.sortByDescending { it.first.length }
            gazetteer.sortByDescending { it.first.length }
            return PoliceStationHomophoneDict(global, gazetteer)
        }
    }

    /** 整句级无条件替换（术语、标点、高置信误识）。 */
    fun applyGlobalPhrases(text: String): String {
        var out = text
        for ((from, to) in globalPhrases) {
            if (from.isEmpty()) continue
            out = out.replace(from, to)
        }
        return out
    }

    /**
     * 站名片段级 gazetteer 约束替换：raw 已是 gazetteer 条目则不动；
     * 否则仅当 from→to 后命中 gazetteer 才应用（支持多轮链式，最多 4 轮）。
     */
    fun applyGazetteerConstrained(raw: String, gazetteer: PoliceStationGazetteer): String {
        if (gazetteer.isKnown(raw)) return raw
        var out = raw
        for (pass in 0 until 4) {
            var changed = false
            for ((from, to) in gazetteerPhrases) {
                if (!out.contains(from)) continue
                val candidate = out.replace(from, to)
                val known = gazetteer.findLongestIn(candidate)
                    ?: candidate.takeIf { gazetteer.isKnown(it) }
                if (known != null) {
                    out = known
                    changed = true
                    if (gazetteer.isKnown(out)) return out
                }
            }
            if (!changed) break
        }
        return out
    }
}
