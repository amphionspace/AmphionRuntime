package com.amphion.police.terms

import android.content.Context
import java.io.BufferedReader
import java.io.InputStreamReader

/** 标准警务术语表（每行一个，按长度降序以便最长匹配）。 */
class PoliceTermsGazetteer(
    private val terms: List<String>,
) {
    companion object {
        private const val ASSET_PATH = "police_terms/term_gazetteer.txt"

        fun load(context: Context): PoliceTermsGazetteer {
            context.assets.open(ASSET_PATH).use { input ->
                return loadFromReader(BufferedReader(InputStreamReader(input, Charsets.UTF_8)))
            }
        }

        fun loadFromReader(reader: BufferedReader): PoliceTermsGazetteer {
            val terms = reader.lineSequence()
                .map { it.trim() }
                .filter { it.isNotEmpty() && !it.startsWith("#") }
                .distinct()
                .sortedByDescending { it.length }
                .toList()
            return PoliceTermsGazetteer(terms)
        }
    }

    fun allTerms(): List<String> = terms

    fun findLongestAt(text: String, start: Int): String? {
        if (start < 0 || start >= text.length) return null
        return terms.firstOrNull { text.startsWith(it, start) }
    }

    fun isKnown(term: String): Boolean = terms.contains(term)
}
