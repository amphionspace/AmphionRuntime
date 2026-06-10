package com.amphion.police.terms

import android.content.Context
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * 警务术语谐音/误识映射：from,to,category（按 from 长度降序替换）。
 */
internal class PoliceTermsHomophoneDict(
    private val phraseMap: List<Pair<String, String>>,
) {
    companion object {
        private const val ASSET_PATH = "police_terms/term_homophones.csv"

        fun load(context: Context): PoliceTermsHomophoneDict {
            context.assets.open(ASSET_PATH).use { input ->
                return loadFromReader(BufferedReader(InputStreamReader(input, Charsets.UTF_8)))
            }
        }

        fun loadFromReader(reader: BufferedReader): PoliceTermsHomophoneDict {
            val pairs = mutableListOf<Pair<String, String>>()
            reader.forEachLine { line ->
                val s = line.trim()
                if (s.isEmpty() || s.startsWith("#")) return@forEachLine
                val parts = s.split(",")
                if (parts.size < 2) return@forEachLine
                val from = parts[0].trim()
                val to = parts[1].trim()
                if (from.isEmpty() || to.isEmpty()) return@forEachLine
                pairs.add(from to to)
            }
            pairs.sortByDescending { it.first.length }
            return PoliceTermsHomophoneDict(pairs)
        }
    }

    fun applyPhrases(text: String): String {
        var out = text
        for ((from, to) in phraseMap) {
            if (from.isEmpty()) continue
            out = out.replace(from, to)
        }
        return out
    }
}
