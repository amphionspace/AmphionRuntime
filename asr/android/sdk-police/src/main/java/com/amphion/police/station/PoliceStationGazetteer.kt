package com.amphion.police.station

import android.content.Context
import java.io.BufferedReader
import java.io.InputStreamReader

/** 标准派出所名称表（每行一个，按长度降序缓存以便最长匹配）。 */
internal class PoliceStationGazetteer(
    private val names: List<String>,
) {
    companion object {
        private const val ASSET_PATH = "police_station/station_gazetteer.txt"

        fun load(context: Context): PoliceStationGazetteer {
            context.assets.open(ASSET_PATH).use { input ->
                return loadFromReader(BufferedReader(InputStreamReader(input, Charsets.UTF_8)))
            }
        }

        fun loadFromReader(reader: BufferedReader): PoliceStationGazetteer {
            val names = reader.lineSequence()
                .map { it.trim() }
                .filter { it.isNotEmpty() && !it.startsWith("#") }
                .distinct()
                .sortedByDescending { it.length }
                .toList()
            return PoliceStationGazetteer(names)
        }
    }

    fun findLongestIn(text: String): String? =
        names.firstOrNull { text.contains(it) }

    fun isKnown(name: String): Boolean = names.contains(name)
}
