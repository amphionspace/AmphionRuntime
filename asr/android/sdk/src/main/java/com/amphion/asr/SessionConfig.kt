package com.amphion.asr

/**
 * 会话级覆盖配置：只覆盖纯运行时阈值参数，按需在 [AsrEngine.newSession] 时传入。
 * null 字段表示沿用 engine 级 [AsrConfig] 的对应值。
 *
 * 设计动机：[VadConfig.activeEndpointSilenceMs]（主动 endpoint 尾静音）与
 * [TargetSpeakerConfig.speakerVad] 的滑窗参数都只是 Kotlin 层阈值，并不参与
 * OnlineRecognizer / silero VAD / 声纹模型的 native 构造。把它们做成会话级覆盖，
 * 同一个 [AsrEngine] 即可逐会话调参，而不必为了改这些值去重建引擎——重建会触发
 * 秒级的 native 冷加载，并在重建窗口内丢失刚到达的音频。
 *
 * @property endpointSilenceMs 覆盖 [VadConfig.activeEndpointSilenceMs]；null = 用 engine 默认
 * @property speakerVad 覆盖 [TargetSpeakerConfig.speakerVad] 滑窗参数；null = 用 engine 默认
 * @property initialSilenceTimeoutMs 首次检测到语音前允许的静音时长；null 或 0 = 禁用
 * @property initialSilenceConfirmationGraceMs 初始等待窗内存在声学活动但 VAD/ASR 尚未确认时，
 *   允许的一次性有界确认窗口；仅配置 target speaker 时生效，并钳制到其 minSegSec；null 或 0 = 不延长
 */
public data class SessionConfig(
    public val endpointSilenceMs: Int? = null,
    public val speakerVad: SpeakerVadConfig? = null,
    public val initialSilenceTimeoutMs: Int? = null,
    public val initialSilenceConfirmationGraceMs: Int? = null,
) {
    init {
        require(endpointSilenceMs == null || endpointSilenceMs >= 0) {
            "SessionConfig.endpointSilenceMs must be >= 0"
        }
        require(initialSilenceTimeoutMs == null || initialSilenceTimeoutMs >= 0) {
            "SessionConfig.initialSilenceTimeoutMs must be >= 0"
        }
        require(initialSilenceConfirmationGraceMs == null || initialSilenceConfirmationGraceMs >= 0) {
            "SessionConfig.initialSilenceConfirmationGraceMs must be >= 0"
        }
    }
}
