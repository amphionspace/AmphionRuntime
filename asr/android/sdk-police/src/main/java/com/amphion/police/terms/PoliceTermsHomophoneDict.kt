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
            if (from.isEmpty() || from == to) continue
            out = if (to.startsWith(from)) {
                replaceExtendingPhrase(out, from, to)
            } else {
                out.replace(from, to)
            }
        }
        return out
    }

    /**
     * from 为 to 的前缀时（如 暂不需要增派警→暂不需要增派警力），
     * 跳过已是完整 to 的片段，避免「增派警力」→「增派警力力」。
     */
    private fun replaceExtendingPhrase(text: String, from: String, to: String): String {
        val sb = StringBuilder()
        var i = 0
        while (i <= text.length) {
            val idx = text.indexOf(from, i)
            if (idx < 0) {
                sb.append(text.substring(i))
                break
            }
            sb.append(text.substring(i, idx))
            if (idx + to.length <= text.length && text.regionMatches(idx, to, 0, to.length)) {
                sb.append(to)
                i = idx + to.length
            } else {
                sb.append(to)
                i = idx + from.length
            }
        }
        return sb.toString()
    }
}
