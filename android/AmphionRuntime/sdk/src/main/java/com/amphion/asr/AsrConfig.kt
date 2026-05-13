package com.amphion.asr

import java.io.File

/**
 * 引擎配置（不可变）。
 *
 * 通过 [Builder] 构造，构造完成后字段不可改；想换配置必须新建一个 [AsrEngine]。
 *
 * 每个 [AsrEngine] 对应一个 [AsrConfig] 实例（一个模型）。
 */
public class AsrConfig private constructor(
    public val modelDir: File,
    public val numThreads: Int,
    public val enableEndpoint: Boolean,
    public val endpointRules: EndpointRules,
    public val hotwords: List<String>,
    public val hotwordsScore: Float,
    public val enableVad: Boolean,
    public val vadModelPath: File?,
    public val sampleRate: Int,
    public val featureDim: Int,
    public val decodingMethod: DecodingMethod,
    public val maxActivePaths: Int,
    /** HomophoneReplacer 词典路径；与 [homophoneRuleFstsPath] 必须同时为 null 或同时非 null。 */
    public val homophoneLexiconPath: File?,
    /** HomophoneReplacer FST 路径。 */
    public val homophoneRuleFstsPath: File?,
    /** ITN（数字归一化等）规则 FST 路径列表，按顺序应用；空列表表示不启用 ITN。 */
    public val itnRuleFstsPaths: List<File>,
    /** LM rescoring 的 ONNX 路径；为 null 表示不启用。仅在 [DecodingMethod.MODIFIED_BEAM_SEARCH] 下生效。 */
    public val lmModelPath: File?,
    /** LM rescoring 权重；建议范围 [0.1, 1.0]，默认 0.5。 */
    public val lmScale: Float,
    /**
     * 标识 [decodingMethod] 是否由调用方显式设置过。仅 SDK 内部用，用来决定
     * 是否被 manifest.json 的 `decoding_method` 字段覆盖。对 Java/外部不可见。
     */
    internal val decodingMethodIsExplicit: Boolean,
    /** 同上，针对 [maxActivePaths]。 */
    internal val maxActivePathsIsExplicit: Boolean,
) {

    /**
     * Builder：链式构造 [AsrConfig]。
     *
     * 必填：[modelDir]，必须包含 `encoder.int8.onnx` / `decoder.onnx` / `joiner.int8.onnx` / `tokens.txt`。
     *
     * 典型用法（Kotlin）：
     * ```
     * val config = AsrConfig.Builder(modelDir)
     *     .numThreads(2)
     *     .enableEndpoint(true)
     *     .hotwords(listOf("声学模型", "语音识别"), score = 1.5f)
     *     .enableVad(File(filesDir, "silero_vad.onnx"))
     *     .build()
     * ```
     *
     * Java 示例：
     * ```
     * AsrConfig config = new AsrConfig.Builder(modelDir)
     *     .numThreads(2)
     *     .enableEndpoint(true)
     *     .build();
     * ```
     */
    public class Builder(private val modelDir: File) {

        private var numThreads: Int = 2
        private var enableEndpoint: Boolean = true
        private var endpointRules: EndpointRules = EndpointRules()
        private var hotwords: List<String> = emptyList()
        private var hotwordsScore: Float = 1.5f
        private var enableVad: Boolean = false
        private var vadModelPath: File? = null
        private var sampleRate: Int = 16000
        private var featureDim: Int = 80
        private var decodingMethod: DecodingMethod = DecodingMethod.GREEDY_SEARCH
        private var decodingMethodExplicit: Boolean = false
        private var maxActivePaths: Int = 4
        private var maxActivePathsExplicit: Boolean = false
        private var homophoneLexiconPath: File? = null
        private var homophoneRuleFstsPath: File? = null
        private var itnRuleFstsPaths: List<File> = emptyList()
        private var lmModelPath: File? = null
        private var lmScale: Float = 0.5f

        /** 推理线程数，默认 2；建议 1~4，超过物理大核数没有收益。 */
        public fun numThreads(value: Int): Builder = apply {
            require(value in 1..8) { "numThreads must be in [1, 8], got $value" }
            this.numThreads = value
        }

        /** 是否启用 endpointing（端点检测自动出 final）。 */
        public fun enableEndpoint(value: Boolean): Builder = apply {
            this.enableEndpoint = value
        }

        /** 自定义 endpointing 规则（高级；不调使用默认值）。 */
        public fun endpointRules(rules: EndpointRules): Builder = apply {
            this.endpointRules = rules
        }

        /**
         * 设置热词列表，提升业务领域内的识别率。
         *
         * @param words 热词字符串列表；中英文皆可，最多建议 200 个
         * @param score 热词加权分数，越大越倾向于命中；默认 1.5；建议范围 [0.5, 3.0]
         */
        @JvmOverloads
        public fun hotwords(words: List<String>, score: Float = 1.5f): Builder = apply {
            require(score in 0.0f..5.0f) { "hotwordsScore must be in [0.0, 5.0]" }
            this.hotwords = words.filter { it.isNotBlank() }
            this.hotwordsScore = score
        }

        /**
         * 启用 VAD（基于 silero VAD）。
         *
         * @param sileroVadModel silero_vad.onnx 文件位置；该文件由集成方下发到本地
         */
        public fun enableVad(sileroVadModel: File): Builder = apply {
            require(sileroVadModel.isFile) {
                "VAD model file does not exist: ${sileroVadModel.absolutePath}"
            }
            this.enableVad = true
            this.vadModelPath = sileroVadModel
        }

        /**
         * 解码方式，默认 [DecodingMethod.GREEDY_SEARCH]。
         *
         * 若调用方未显式设置，SDK 会优先使用 modelDir/manifest.json 中的 `decoding_method` 字段；
         * 仍未提供则用此默认值。详见 INTEGRATION.md 第 7 节。
         */
        public fun decodingMethod(value: DecodingMethod): Builder = apply {
            this.decodingMethod = value
            this.decodingMethodExplicit = true
        }

        /**
         * [DecodingMethod.MODIFIED_BEAM_SEARCH] 时的 beam size，默认 4，建议 [1, 8]。
         *
         * 若调用方未显式设置，SDK 会优先使用 modelDir/manifest.json 中的 `max_active_paths` 字段（如果存在）；
         * 仍未提供则用此默认值。
         */
        public fun maxActivePaths(value: Int): Builder = apply {
            require(value in 1..32) { "maxActivePaths must be in [1, 32]" }
            this.maxActivePaths = value
            this.maxActivePathsExplicit = true
        }

        /**
         * 启用同音字纠错（HomophoneReplacer）。
         *
         * 中文场景非常实用：把 ASR 输出中的同音错误（"在线" -> "再线"）按词典 + 规则 FST 自动改回。
         *
         * @param lexicon 词典文件，每行 `key\\t<homophone>...` 格式
         * @param ruleFsts FST 文件，sherpa-onnx 自带的同音替换规则
         */
        public fun enableHomophoneReplacer(lexicon: File, ruleFsts: File): Builder = apply {
            require(lexicon.isFile) { "lexicon not found: ${lexicon.absolutePath}" }
            require(ruleFsts.isFile) { "ruleFsts not found: ${ruleFsts.absolutePath}" }
            this.homophoneLexiconPath = lexicon
            this.homophoneRuleFstsPath = ruleFsts
        }

        /**
         * 启用文本归一化（ITN: Inverse Text Normalization），把"二零二六年"转写成 "2026 年"等。
         *
         * @param ruleFsts 1 个或多个 FST 路径；按列表顺序串行应用
         */
        public fun enableInverseTextNormalization(ruleFsts: List<File>): Builder = apply {
            require(ruleFsts.isNotEmpty()) { "at least one ITN rule fst is required" }
            for (f in ruleFsts) require(f.isFile) { "ITN fst not found: ${f.absolutePath}" }
            this.itnRuleFstsPaths = ruleFsts.toList()
        }

        /** 单 FST 便捷重载。 */
        public fun enableInverseTextNormalization(ruleFst: File): Builder =
            enableInverseTextNormalization(listOf(ruleFst))

        /**
         * 启用神经网络语言模型重打分（LM rescoring）。
         *
         * 仅在 [DecodingMethod.MODIFIED_BEAM_SEARCH] 下生效；如果当前是 GREEDY_SEARCH，
         * SDK 会自动切换到 modified_beam_search（与 hotwords 协商一致）。
         *
         * @param modelPath RNN-LM ONNX 路径
         * @param scale LM 权重，建议 [0.1, 1.0]，默认 0.5
         */
        @JvmOverloads
        public fun enableLmRescoring(modelPath: File, scale: Float = 0.5f): Builder = apply {
            require(modelPath.isFile) { "LM model not found: ${modelPath.absolutePath}" }
            require(scale in 0.0f..2.0f) { "lmScale must be in [0.0, 2.0]" }
            this.lmModelPath = modelPath
            this.lmScale = scale
        }

        public fun build(): AsrConfig {
            require(modelDir.isDirectory) { "modelDir not a directory: ${modelDir.absolutePath}" }
            // 注意：单文件存在性校验放到 EngineImpl 中按 model_type 做（不同模型族需要的文件清单不同）。
            // 这里只确保 tokens.txt 一定要在（所有 model_type 共用）。
            require(File(modelDir, "tokens.txt").isFile) {
                "missing tokens.txt under ${modelDir.absolutePath}"
            }

            // 上游 sherpa-onnx 强制：hotwords / LM rescoring 仅在 modified_beam_search 下生效
            // （online-recognizer.cc 会 LOGE 并 reject 掉 greedy_search + hotwords / lm 的组合）。
            // 这里做一次"用户友好"协商：
            //   - 如果热词或 LM 非空且调用方没显式指定 decodingMethod：自动切到 MODIFIED_BEAM_SEARCH
            //   - 如果调用方显式选了 GREEDY_SEARCH：直接 fail-fast
            var effectiveDecoding = decodingMethod
            var effectiveDecodingExplicit = decodingMethodExplicit
            val needsBeam = hotwords.isNotEmpty() || lmModelPath != null
            if (needsBeam) {
                if (!decodingMethodExplicit) {
                    effectiveDecoding = DecodingMethod.MODIFIED_BEAM_SEARCH
                    effectiveDecodingExplicit = true
                } else {
                    require(decodingMethod == DecodingMethod.MODIFIED_BEAM_SEARCH) {
                        "hotwords / LM rescoring require decodingMethod=MODIFIED_BEAM_SEARCH; " +
                            "either drop them or remove the explicit GREEDY_SEARCH override."
                    }
                }
            }

            // HomophoneReplacer 必须 lexicon 与 ruleFsts 配对
            require((homophoneLexiconPath == null) == (homophoneRuleFstsPath == null)) {
                "enableHomophoneReplacer must be called with both lexicon and ruleFsts (or neither)."
            }

            return AsrConfig(
                modelDir = modelDir,
                numThreads = numThreads,
                enableEndpoint = enableEndpoint,
                endpointRules = endpointRules,
                hotwords = hotwords,
                hotwordsScore = hotwordsScore,
                enableVad = enableVad,
                vadModelPath = vadModelPath,
                sampleRate = sampleRate,
                featureDim = featureDim,
                decodingMethod = effectiveDecoding,
                maxActivePaths = maxActivePaths,
                homophoneLexiconPath = homophoneLexiconPath,
                homophoneRuleFstsPath = homophoneRuleFstsPath,
                itnRuleFstsPaths = itnRuleFstsPaths,
                lmModelPath = lmModelPath,
                lmScale = lmScale,
                decodingMethodIsExplicit = effectiveDecodingExplicit,
                maxActivePathsIsExplicit = maxActivePathsExplicit,
            )
        }
    }
}

/** 解码方式。 */
public enum class DecodingMethod {
    /** 贪心解码：最快，质量足够。 */
    GREEDY_SEARCH,

    /** modified_beam_search：质量略高，速度慢 ~2x；可与 [AsrConfig.Builder.maxActivePaths] 调节。 */
    MODIFIED_BEAM_SEARCH,
}

/**
 * Endpointing 规则集合（默认值与 sherpa-onnx 官方流式默认一致）。
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
