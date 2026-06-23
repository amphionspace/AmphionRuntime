package com.amphion.police.terms

/**
 * 警务术语场景默认热词（解码阶段偏置，与 [PoliceTermsNormalizer] 互补）。
 */
object PoliceTermsHotwords {

    val PRESET: List<String> = listOf(
        // 甲方真人测：语音指令
        // 注：刻意不收录「打开X」「帮我打开X」这类含动词前缀的多字热词。它们会让解码把
        // 「帮我打开/打开」前缀强行偏置，截断「帮我打开设置/计算器」等其它「打开X」指令的尾巴。
        // 「打开景信→打开警信」等谐音纠正已由 term_homophones.csv 后处理覆盖，无需解码期偏置。
        "警信",
        "时钟",
        "启动帮写功能",
        "启动帮填功能",
        "帮写功能",
        "帮填功能",
        "群访群治",
        "待办公文",
        "待办",
        "情指中心",
        "到岗",
        "WeConmm",
        "创建警单",
        "查看报警现场视频",
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
