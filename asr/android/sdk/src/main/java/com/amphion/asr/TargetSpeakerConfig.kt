package com.amphion.asr

/**
 * 目标说话人能力配置（形态A 输出门控）。挂在 [AsrConfig] 上声明 engine 是否具备目标说话人能力。
 *
 * 注意：声明本配置只是让 engine 加载声纹模型、具备打分能力；运行时是否真正过滤，由
 * [AsrSession.setTargetSpeakerEnabled] 与是否已 [AsrSession.setTargetSpeaker] 共同决定。
 *
 * 语义为输出门控：ASR 始终流式全量识别（onPartial 不变），声纹只在每段话结束时对该段音频
 * 打一次分；开关开启且已注册目标时，非目标段的 [AsrCallback.onFinal] 默认不触发（改触发
 * [AsrCallback.onFinalRejected]）。
 *
 * @property modelPath 声纹 embedding ONNX 模型的绝对路径（如 3D-Speaker eres2net，约 27 MB）。
 *   当前默认走业务提供的外部文件路径，不随 AAR 内置
 * @property threshold 目标判定的余弦相似度阈值，[-1.0, 1.0]；>= 阈值判为目标。默认 0.30
 *   （对应调研评测 FAR≈3.96% / FRR≈10.55% 的保守点）；正式上线前应按真机数据标定回填
 * @property winSec 滑窗打分的窗长（秒），默认 2.5
 * @property hopSec 滑窗步长（秒），默认 1.0
 * @property minSegSec 最短判定切片（秒）；段长不足时不打分（视为无法判定），默认 1.5
 * @property preload true 时随 [AmphionRuntime.create] 即加载声纹模型，运行时开关只切标志位
 *   （秒级生效）；false 时首次 [AsrSession.setTargetSpeakerEnabled] 为 true 才懒加载（首次有加载延迟）
 * @property enabledByDefault 新建 [AsrSession] 时开关的初始状态，默认 false
 * @property numThreads 声纹推理线程数，[1, 8]，默认 1
 * @property speakerVad 目标说话人 VAD 配置；null 表示不启用“目标人离场提前 endpoint”能力
 */
public data class TargetSpeakerConfig(
    public val modelPath: String,
    public val threshold: Float = 0.30f,
    public val winSec: Float = 2.5f,
    public val hopSec: Float = 1.0f,
    public val minSegSec: Float = 1.5f,
    public val preload: Boolean = false,
    public val enabledByDefault: Boolean = false,
    public val numThreads: Int = 1,
    public val speakerVad: SpeakerVadConfig? = null,
) {
    init {
        require(modelPath.isNotBlank()) { "TargetSpeakerConfig.modelPath must not be blank" }
        require(threshold in -1.0f..1.0f) {
            "TargetSpeakerConfig.threshold must be in [-1.0, 1.0], got $threshold"
        }
        require(winSec > 0f) { "TargetSpeakerConfig.winSec must be > 0" }
        require(hopSec > 0f) { "TargetSpeakerConfig.hopSec must be > 0" }
        require(minSegSec > 0f) { "TargetSpeakerConfig.minSegSec must be > 0" }
        require(numThreads in 1..8) {
            "TargetSpeakerConfig.numThreads must be in [1, 8], got $numThreads"
        }
    }
}

/**
 * 目标说话人 VAD 配置。
 *
 * 语义不是过滤最终结果，而是在 VAD 已检测到 speech 后，对当前 utterance 尾部滑窗做声纹相似度
 * 判定：先确认目标人开口，再在连续低于阈值时主动 endpoint，让下游尽早拿到 final。
 *
 * @property threshold 当前滑窗余弦相似度阈值；低于该值计一次“目标人离场”
 * @property winSec 单次声纹打分窗长（秒）。越短响应越快但越不稳，默认 1.5s
 * @property hopSec 滑窗打分步长（秒）。越短响应越快但推理开销越高，默认 0.5s
 * @property consecutiveBelow 连续多少个低分窗口后触发 endpoint，默认 2
 * @property enabledByDefault 新建 [AsrSession] 时 speaker vad 的初始状态，默认 false
 */
public data class SpeakerVadConfig(
    public val threshold: Float = 0.35f,
    public val winSec: Float = 1.5f,
    public val hopSec: Float = 0.5f,
    public val consecutiveBelow: Int = 2,
    public val enabledByDefault: Boolean = false,
) {
    init {
        require(threshold in -1.0f..1.0f) {
            "SpeakerVadConfig.threshold must be in [-1.0, 1.0], got $threshold"
        }
        require(winSec > 0f) { "SpeakerVadConfig.winSec must be > 0" }
        require(hopSec > 0f) { "SpeakerVadConfig.hopSec must be > 0" }
        require(consecutiveBelow >= 1) {
            "SpeakerVadConfig.consecutiveBelow must be >= 1, got $consecutiveBelow"
        }
    }
}
