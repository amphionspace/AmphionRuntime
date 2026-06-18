package com.amphion.asr

/**
 * 业务方在创建 [AsrEngine] 时选择的语言场景。
 *
 * 同一份 SDK AAR 内已经把所有支持的语言模型一并打进 assets，调用方只声明业务语言，
 * SDK 内部负责加载对应的 ASR / 标点 / ITN 模型组合。
 */
public enum class AsrLanguage {

    /** 中英混合（CMN + EN）。支持标点 + ITN + VAD。 */
    ZH_EN,

    /**
     * 粤英混合（YUE + EN）。支持标点 + VAD；ITN 暂仅对中文场景启用，
     * 在粤英下设置 [AsrConfig.itn] = true 也会被忽略。
     */
    YUE_EN,
}
