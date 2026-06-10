package com.amphion.asr.sample.police_station

/**
 * 派出所场景默认热词（解码阶段偏置，与 [PoliceStationNormalizer] 互补）。
 */
object PoliceStationHotwords {

    val PRESET: List<String> = listOf(
        "派出所",
        "接警",
        "观音桥派出所",
        "中关村派出所",
        "五角场派出所",
        "解放碑派出所",
        "中央大街派出所",
        "绳金塔派出所",
        "张掖路派出所",
        "泉城路派出所",
    )

    fun mergeWithUserWords(userWords: List<String>, includePreset: Boolean): List<String> {
        if (!includePreset) return userWords.filter { it.isNotBlank() }.distinct()
        val out = linkedSetOf<String>()
        userWords.filter { it.isNotBlank() }.forEach { out.add(it.trim()) }
        PRESET.forEach { out.add(it) }
        return out.toList()
    }
}
