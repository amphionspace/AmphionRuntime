package com.amphion.asr.sample.plate

/**
 * 车牌场景默认热词（对齐云端 bench：冀R/辽B 等前缀偏置 + 车牌语境词）。
 *
 * 在 ASR 解码阶段生效，减轻「冀→J / GR」「辽币」等误听，与 [PlateNormalizer] 互补。
 */
object PlateHotwords {

    /** 与 KeSpeech 车牌子集及警用查询句式对齐的固定热词。 */
    val PRESET: List<String> = listOf(
        "冀R",
        "辽B",
        "车牌号",
        "车牌号码",
        "车牌",
        "牌照",
    )

    fun mergeWithUserWords(userWords: List<String>, includePreset: Boolean): List<String> {
        if (!includePreset) return userWords.filter { it.isNotBlank() }.distinct()
        val out = linkedSetOf<String>()
        userWords.filter { it.isNotBlank() }.forEach { out.add(it.trim()) }
        PRESET.forEach { out.add(it) }
        return out.toList()
    }
}
