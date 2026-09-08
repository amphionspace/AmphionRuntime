package com.amphion.police.plate

import android.content.Context
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * 仅纠正完整 final 的已知车牌残差。
 *
 * 这些样本包含丢字、增字和整段错听，无法从任意车牌文本中安全泛化。与通用 GA36 解码分开，
 * 可以保证相同片段出现在产品编号、复述句或其他上下文时不被强制改写。
 */
internal class PlateExactResidualDict private constructor(
    private val wholeUtteranceMap: Map<String, String>,
) {
    data class Match(
        val start: Int,
        val end: Int,
        val raw: String,
        val normalized: String,
    )

    companion object {
        const val ASSET_PATH = "plate/plate_exact_residuals.csv"

        val EMPTY = PlateExactResidualDict(emptyMap())

        fun load(context: Context): PlateExactResidualDict =
            context.assets.open(ASSET_PATH).use { input ->
                loadFromReader(BufferedReader(InputStreamReader(input, Charsets.UTF_8)))
            }

        fun loadFromReader(reader: BufferedReader): PlateExactResidualDict {
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
            return PlateExactResidualDict(mappings)
        }
    }

    private val sentenceEndChars =
        setOf('。', '！', '？', '!', '?', '，', ',', '、', '；', ';', '：', ':')

    fun matchWholeUtterance(text: String): Match? {
        val start = text.indexOfFirst { !it.isWhitespace() }.takeIf { it >= 0 } ?: return null
        var end = text.length
        while (end > start) {
            val value = text[end - 1]
            if (!value.isWhitespace() && value !in sentenceEndChars) break
            end--
        }
        if (end <= start) return null
        val raw = text.substring(start, end)
        val normalized = wholeUtteranceMap[raw] ?: return null
        return Match(start, end, raw, normalized)
    }
}
