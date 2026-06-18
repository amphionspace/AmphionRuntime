package com.amphion.police.terms

/**
 * 警务术语场景默认热词（解码阶段偏置，与 [PoliceTermsNormalizer] 互补）。
 */
object PoliceTermsHotwords {

    val PRESET: List<String> = listOf(
        // 甲方真人测：语音指令
        "帮我打开警信",
        "帮我打开时钟",
        "打开警信",
        "警信",
        "启动帮写功能",
        "打开帮填功能",
        "启动帮填功能",
        "帮写功能",
        "帮填功能",
        // P0/P1：警单系长短语优先
        "签收警单",
        "签收警单后",
        "已签收警单",
        "签收警情",
        "已签收警情",
        "警单",
        // P2：处警系
        "处警",
        "处警人员",
        "处警过程中",
        "正在处警",
        // P3：接警系
        "接警",
        "已接警",
        "接警台",
        "接警时已确认",
        // P4
        "报警人",
        // P5
        "街面巡逻组",
        "社区警务队",
        // VD round03：增派截断短语（解码偏置）
        "暂不需要增派警力",
        "已请求增派警力",
        // 其他高频术语
        "增派警力",
        "警情",
        "警力",
        "派警",
        "联勤",
        "处警车辆",
    )

    fun mergeWithUserWords(userWords: List<String>, includePreset: Boolean): List<String> {
        if (!includePreset) return userWords.filter { it.isNotBlank() }.distinct()
        val out = linkedSetOf<String>()
        userWords.filter { it.isNotBlank() }.forEach { out.add(it.trim()) }
        PRESET.forEach { out.add(it) }
        return out.toList()
    }
}
