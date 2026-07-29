package com.amphion.asr

/**
 * 引擎配置（不可变）。模型路径 / decoding / sampleRate 等内部细节由 SDK 自己决定，
 * 业务方只调本类暴露的少量行为开关。
 *
 * 通过 [Builder] 链式构造。
 *
 * 典型用法（Kotlin）：
 * ```
 * val config = AsrConfig.Builder()
 *     .numThreads(2)
 *     .punctuation(true)
 *     .itn(true)
 *     .vad(true)
 *     .endpoint(true)
 *     .hotwords(listOf("声学模型", "语音识别"))
 *     .build()
 * ```
 *
 * 默认值：所有开关都为 true，[numThreads] = 2，[hotwords] 为空。
 *
 * @property numThreads 推理线程数，建议 1~4
 * @property punctuation 是否给 final 文本加标点（中英 + 粤英 都生效）
 * @property itn 是否对 final 做中文 ITN（口语数字 -> 阿拉伯数字 / 单位）。
 *   仅 [AsrLanguage.ZH_EN] 生效；其他语言会被忽略
 * @property vad 是否启用 VAD：0.2.x 起 SDK 把 silero VAD 真实接入流式管线——
 *   在 ASR 之上做 Gate + 主动 endpoint，比 [endpointRules] 的尾静音规则更敏感，
 *   显著缓解长句子说到一半不切分的问题。具体行为由 [vadConfig] 调
 * @property vadConfig VAD 细节配置（模型 / 阈值 / 主动 endpoint 静音时长等）
 * @property endpoint 是否启用端点检测自动出 final
 * @property endpointRules 端点规则细节，默认与上游 sherpa-onnx 流式默认一致
 * @property hotwords 热词列表，提升业务领域词识别率
 * @property hotwordsScore 热词加权分数，[0.0, 5.0]，越大越倾向于命中
 * @property targetSpeaker 目标说话人能力配置；null 表示不启用（默认）。详见 [TargetSpeakerConfig]
 * @property disablePrepack 是否跳过 ORT INT8 权重 prepack；默认 true，以降低冷加载时间和峰值内存
 */
public class AsrConfig private constructor(
    public val numThreads: Int,
    public val punctuation: Boolean,
    public val itn: Boolean,
    public val vad: Boolean,
    public val vadConfig: VadConfig,
    public val endpoint: Boolean,
    public val endpointRules: EndpointRules,
    public val hotwords: List<String>,
    public val hotwordsScore: Float,
    public val targetSpeaker: TargetSpeakerConfig?,
    public val disablePrepack: Boolean,
) {

    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is AsrConfig) return false

        return numThreads == other.numThreads &&
            punctuation == other.punctuation &&
            itn == other.itn &&
            vad == other.vad &&
            vadConfig == other.vadConfig &&
            endpoint == other.endpoint &&
            endpointRules == other.endpointRules &&
            hotwords == other.hotwords &&
            hotwordsScore == other.hotwordsScore &&
            targetSpeaker == other.targetSpeaker &&
            disablePrepack == other.disablePrepack
    }

    override fun hashCode(): Int {
        var result = numThreads
        result = 31 * result + punctuation.hashCode()
        result = 31 * result + itn.hashCode()
        result = 31 * result + vad.hashCode()
        result = 31 * result + vadConfig.hashCode()
        result = 31 * result + endpoint.hashCode()
        result = 31 * result + endpointRules.hashCode()
        result = 31 * result + hotwords.hashCode()
        result = 31 * result + hotwordsScore.hashCode()
        result = 31 * result + (targetSpeaker?.hashCode() ?: 0)
        result = 31 * result + disablePrepack.hashCode()
        return result
    }

    /**
     * Builder：链式构造 [AsrConfig]。
     *
     * Java 示例：
     * ```
     * AsrConfig config = new AsrConfig.Builder()
     *     .numThreads(2)
     *     .punctuation(true)
     *     .itn(true)
     *     .vad(true)
     *     .build();
     * ```
     */
    public class Builder {

        private var numThreads: Int = 2
        private var punctuation: Boolean = true
        private var itn: Boolean = true
        private var vad: Boolean = true
        private var vadConfig: VadConfig = VadConfig()
        private var endpoint: Boolean = true
        private var endpointRules: EndpointRules = EndpointRules()
        private var hotwords: List<String> = emptyList()
        private var hotwordsScore: Float = 1.5f
        private var targetSpeaker: TargetSpeakerConfig? = null
        private var disablePrepack: Boolean = true

        /** 推理线程数，[1, 8]；默认 2，建议 1~4。 */
        public fun numThreads(value: Int): Builder = apply {
            require(value in 1..8) { "numThreads must be in [1, 8], got $value" }
            this.numThreads = value
        }

        /** 是否给 final 文本加标点（默认 true，中英 + 粤英 都生效）。 */
        public fun punctuation(value: Boolean): Builder = apply {
            this.punctuation = value
        }

        /**
         * 是否对 final 做中文 ITN（默认 true）。
         *
         * 仅 [AsrLanguage.ZH_EN] 生效；其他语言会自动忽略本开关。
         */
        public fun itn(value: Boolean): Builder = apply {
            this.itn = value
        }

        /**
         * 是否启用 VAD（默认 true）。
         *
         * 0.2.x 起 SDK 把 silero VAD 真实接入流式管线：在 ASR 之上做 Gate + 主动 endpoint，
         * 比 [endpointRules] 的尾静音规则更敏感（默认 500ms 主动切，而 endpoint rule2 是 1.4s），
         * 显著缓解长句子说到一半不切分的问题。关闭后 PCM 全量送进 ASR，分句只能靠 endpoint。
         */
        public fun vad(value: Boolean): Builder = apply {
            this.vad = value
        }

        /**
         * 调整 VAD 细节（模型选择 / 阈值 / 主动 endpoint 静音时长等）。
         *
         * 高级；不调使用默认值。仅在 [vad] 为 true 时生效。
         */
        public fun vadConfig(config: VadConfig): Builder = apply {
            this.vadConfig = config
        }

        /** 是否启用端点检测自动出 final（默认 true）。 */
        public fun endpoint(value: Boolean): Builder = apply {
            this.endpoint = value
        }

        /** 自定义端点规则（高级；不调使用默认值）。 */
        public fun endpointRules(rules: EndpointRules): Builder = apply {
            this.endpointRules = rules
        }

        /**
         * 设置热词列表，提升业务领域内的识别率。
         *
         * @param words 中英文热词皆可，建议不超过 200 个；空字符串会被自动过滤
         * @param score 热词加权分数，越大越倾向于命中；默认 1.5（沿用 sherpa-onnx 英文场景）；
         *   实际经验值：
         *   - 0.5 ~ 1.5：泛领域词、训练语料里高频出现，少量 boost 就够
         *   - 2.0 ~ 3.0：人名 / 专名 / 同音字纠错（如把「余明洞」纠为「余铭栋」），推荐起步
         *   - 3.0 ~ 5.0：罕见词、训练数据里几乎没见过的命名实体；过大会误伤无关音节
         */
        @JvmOverloads
        public fun hotwords(words: List<String>, score: Float = 1.5f): Builder = apply {
            require(score in 0.0f..5.0f) { "hotwordsScore must be in [0.0, 5.0]" }
            this.hotwords = words.filter { it.isNotBlank() }
            this.hotwordsScore = score
        }

        /**
         * 声明目标说话人能力（默认 null 不启用）。
         *
         * 启用后 engine 会按 [TargetSpeakerConfig] 加载声纹模型；运行时是否真正过滤，由
         * [AsrSession.setTargetSpeakerEnabled] 与是否已 [AsrSession.setTargetSpeaker] 共同决定。
         */
        public fun targetSpeaker(config: TargetSpeakerConfig?): Builder = apply {
            this.targetSpeaker = config
        }

        /** 是否跳过 ORT INT8 权重 prepack；默认 true，优先降低冷加载时间和峰值内存。 */
        public fun disablePrepack(value: Boolean): Builder = apply {
            this.disablePrepack = value
        }

        public fun build(): AsrConfig = AsrConfig(
            numThreads = numThreads,
            punctuation = punctuation,
            itn = itn,
            vad = vad,
            vadConfig = vadConfig,
            endpoint = endpoint,
            endpointRules = endpointRules,
            hotwords = hotwords,
            hotwordsScore = hotwordsScore,
            targetSpeaker = targetSpeaker,
            disablePrepack = disablePrepack,
        )
    }
}

/**
 * VAD 选用的模型。
 *
 * - [SILERO] Silero VAD，默认。模型已内置在 AAR `amphion-models/vad/v1/silero_vad.onnx`，
 *   近场录音场景已足够，约 2 MB
 * - [TEN_VAD] Ten-VAD。在低 SNR / 远场场景识别更鲁棒；**当前 AAR 未打包资产**，
 *   选择后会在 `AmphionRuntime.create` 时抛 [UnsupportedOperationException]
 */
public enum class VadModelType {
    SILERO,
    TEN_VAD,
}

/**
 * VAD 细节配置（不可变）。
 *
 * 默认值对应 sherpa-onnx 1.13.x 上 silero VAD 的安全档；业务方一般不需要调，
 * 只有在「长句子说一半不切分」「停顿被误切」「嘈杂场景误激发」时再针对性调。
 *
 * 与 [EndpointRules] 的区别：endpointRules 控制流式 ASR 自身的端点检测（粗粒度），
 * 本类控制 VAD 这一层（细粒度）；两者叠加生效，谁先触发以谁为准。
 *
 * @property modelType VAD 模型，默认 [VadModelType.SILERO]；选 [VadModelType.TEN_VAD]
 *   而 AAR 未打包对应资产时会抛 [UnsupportedOperationException]
 * @property threshold speech 概率阈值 [0.0, 1.0]，越大越严格；默认 0.5
 * @property minSilenceDurationSec 尾部静音至少持续此值才视为一段语音结束，默认 0.25 秒
 * @property minSpeechDurationSec 一段语音至少持续此值才视为有效，默认 0.25 秒
 * @property maxSpeechDurationSec 单段语音超过此值时 VAD 内部会强制切；默认 15 秒，
 *   比 [EndpointRules.rule3MinUtteranceLengthSec] 的 20 秒更早兜底
 * @property activeEndpointSilenceMs **主动 endpoint 机制**：VAD 检测到 speech 之后
 *   尾部连续静音达到此毫秒数，SDK 会主动给 ASR 出 final（不等 endpoint rule2 的 1.4 秒）。
 *   默认 500 ms；设 0 表示禁用主动 endpoint，仅做 gate；建议范围 [200, 1500]
 */
public data class VadConfig(
    public val modelType: VadModelType = VadModelType.SILERO,
    public val threshold: Float = 0.5f,
    public val minSilenceDurationSec: Float = 0.25f,
    public val minSpeechDurationSec: Float = 0.25f,
    public val maxSpeechDurationSec: Float = 15.0f,
    public val activeEndpointSilenceMs: Int = 500,
) {
    init {
        require(threshold in 0.0f..1.0f) { "VadConfig.threshold must be in [0.0, 1.0], got $threshold" }
        require(minSilenceDurationSec >= 0f) { "VadConfig.minSilenceDurationSec must be >= 0" }
        require(minSpeechDurationSec >= 0f) { "VadConfig.minSpeechDurationSec must be >= 0" }
        require(maxSpeechDurationSec > 0f) { "VadConfig.maxSpeechDurationSec must be > 0" }
        require(activeEndpointSilenceMs >= 0) {
            "VadConfig.activeEndpointSilenceMs must be >= 0 (0 disables active endpoint)"
        }
    }
}

/**
 * 端点检测规则集合（默认与上游 sherpa-onnx 流式默认一致）。
 *
 * @property rule1 一段话开始之后，无静音超过 [rule1MinTrailingSilenceSec] 秒就出 final
 * @property rule1MinTrailingSilenceSec 默认 2.4 秒
 * @property rule2 任意时刻只要曾经出过非静音、且尾部静音超过 [rule2MinTrailingSilenceSec] 秒就出 final
 * @property rule2MinTrailingSilenceSec 默认 1.4 秒
 * @property rule3MinUtteranceLengthSec 整段话超过这个长度强制出 final，默认 20 秒
 */
public data class EndpointRules(
    public val rule1: Boolean = true,
    public val rule1MinTrailingSilenceSec: Float = 2.4f,
    public val rule2: Boolean = true,
    public val rule2MinTrailingSilenceSec: Float = 1.4f,
    public val rule3MinUtteranceLengthSec: Float = 20.0f,
)
