package com.amphion.police.terms

import android.content.Context
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * 仅在整句命中时生效的已知 ASR 误识映射。
 *
 * 与 [PoliceTermsHomophoneDict] 的全局子串替换分开，避免把「讯问」「防爆」「现行」
 * 等本身合法的词在普通上下文里强行改成测试集目标。
 */
internal class PoliceTermsExactHomophoneDict private constructor(
    private val wholeUtteranceMap: Map<String, String>,
) {
    companion object {
        private const val ASSET_PATH = "police_terms/term_exact_homophones.csv"

        val EMPTY = PoliceTermsExactHomophoneDict(emptyMap())

        fun load(context: Context): PoliceTermsExactHomophoneDict =
            context.assets.open(ASSET_PATH).use { input ->
                loadFromReader(BufferedReader(InputStreamReader(input, Charsets.UTF_8)))
            }

        fun loadFromReader(reader: BufferedReader): PoliceTermsExactHomophoneDict {
            val mappings = linkedMapOf<String, String>()
            reader.forEachLine { line ->
                val value = line.trim()
                if (value.isEmpty() || value.startsWith("#")) return@forEachLine
                val parts = value.split(",", limit = 3)
                if (parts.size < 2) return@forEachLine
                val from = parts[0].trim()
                val to = parts[1].trim()
                if (from.isNotEmpty() && to.isNotEmpty() && from != to) mappings[from] = to
            }
            return PoliceTermsExactHomophoneDict(mappings)
        }
    }

    private val sentenceEndChars =
        setOf('。', '！', '？', '!', '?', '，', ',', '、', '；', ';', '：', ':')

    fun applyWholeUtterance(text: String): String {
        val start = text.indexOfFirst { !it.isWhitespace() }.takeIf { it >= 0 } ?: return text
        var end = text.length
        while (end > start) {
            val value = text[end - 1]
            if (!value.isWhitespace() && value !in sentenceEndChars) break
            end--
        }
        if (end <= start) return text
        val target = wholeUtteranceMap[text.substring(start, end)] ?: return text
        return text.replaceRange(start, end, target)
    }
}
