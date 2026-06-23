package com.amphion.police.plate

/**
 * 车牌场景默认热词（对齐云端 bench：冀R/辽B 等前缀偏置 + 车牌语境词）。
 *
 * 在 ASR 解码阶段生效，减轻「冀→J / GR」「辽币」等误听，与 [PlateNormalizer] 互补。
 *
 * 注意：`冀R`/`辽B` 前缀偏置词**保留**——真机 A/B 实测它主要作用是把省份字锚定为 辽/冀
 * （否则易被听成同音 聊/料/济），净收益为正。但热词加权分必须用中档（见
 * [com.amphion.police.PoliceEngineConfig.HOTWORDS_SCORE_DEFAULT]=3.0）：满分 5.0 会过度
 * 偏置权威字母，把 辽F/辽G/辽P 误拉成 辽B；3.0 既保省份锚定又消除该过度纠偏。
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
