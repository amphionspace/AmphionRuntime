package com.amphion.asr.sample.plate

import android.content.Context
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * 从 assets CSV 加载谐音映射：from,to,category
 */
internal class PlateHomophoneDict(
    val charMap: Map<Char, Char>,
) {
    companion object {
        private const val ASSET_PATH = "plate/plate_homophones.csv"

        fun load(context: Context): PlateHomophoneDict {
            context.assets.open(ASSET_PATH).use { input ->
                return loadFromReader(BufferedReader(InputStreamReader(input, Charsets.UTF_8)))
            }
        }

        fun loadFromReader(reader: BufferedReader): PlateHomophoneDict {
            val map = linkedMapOf<Char, Char>()
            reader.forEachLine { line ->
                val s = line.trim()
                if (s.isEmpty() || s.startsWith("#")) return@forEachLine
                val parts = s.split(",")
                if (parts.size < 2) return@forEachLine
                val from = parts[0].trim()
                val to = parts[1].trim()
                if (from.length != 1 || to.length != 1) return@forEachLine
                map[from[0]] = to[0]
            }
            return PlateHomophoneDict(map)
        }
    }

    fun mapChar(c: Char): Char = charMap[c] ?: c
}
