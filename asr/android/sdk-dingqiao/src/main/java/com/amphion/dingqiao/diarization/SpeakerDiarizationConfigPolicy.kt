package com.amphion.dingqiao.diarization

import com.amphion.dingqiao.SpeakerDiarizationConfig

/** 角色身份的来源。与鸿蒙 `SpeakerDiarizationConfigPolicy.ts` 同一组取值。 */
internal object SpeakerIdentityModes {
    /** 沿用 Sortformer 到达顺序槽位（0.3.26 行为）。 */
    const val MODEL = "model"
    /** 按发言段用声纹嵌入判身份（默认）。 */
    const val VOICEPRINT = "voiceprint"
    val ALL = listOf(MODEL, VOICEPRINT)
}

/** 校验 `maxSpeakers` 与 `speakerIdentityMode`，返回归一后的身份来源。 */
internal fun validateSpeakerDiarizationConfig(config: SpeakerDiarizationConfig): String {
    require(config.maxSpeakers in 1..4) {
        "SpeakerDiarizationConfig.maxSpeakers must be in [1, 4]"
    }
    return validateSpeakerIdentityMode(config.speakerIdentityMode)
}

/**
 * 校验并归一身份来源。空串视为未设置，返回 'voiceprint'；'model' 为 0.3.26 行为的显式回退。
 *
 * 拼错的值必须抛错而不是静默回落到 'model'：那会让调用方以为打开了声纹身份、而实际跑的
 * 还是模型槽位，现场排查时极难发现。与鸿蒙 `validateSpeakerIdentityMode` 同一规则。
 */
internal fun validateSpeakerIdentityMode(mode: String?): String {
    if (mode.isNullOrEmpty()) return SpeakerIdentityModes.VOICEPRINT
    require(mode in SpeakerIdentityModes.ALL) {
        "SpeakerDiarizationConfig.speakerIdentityMode must be one of ${SpeakerIdentityModes.ALL.joinToString(", ")}"
    }
    return mode
}
