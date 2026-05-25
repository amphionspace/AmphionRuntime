package com.amphion.asr

import java.io.File

/**
 * 标点引擎配置（不可变）。
 *
 * 通过 [Builder] 构造，构造完成后字段不可改；如需更换模型 / 线程数必须新建一个 [PunctuationEngine]。
 *
 * 配置只描述「用哪一份模型 + 用几条线程」，不耦合 [AsrConfig]：标点引擎独立于 ASR 引擎，
 * 调用方可以按业务需要 lazy 创建 / 单独 close，标点失败不会影响 ASR 主路径。
 *
 * 当前 SDK 支持的标点模型族：
 * - sherpa-onnx CT-Transformer offline 标点（中英双语，约 62 MB INT8）
 *
 * 详见 [docs/INTEGRATION.md](../../../../../../../../../../docs/INTEGRATION.md) §12.6。
 */
public class PunctuationConfig private constructor(
    /** CT-Transformer ONNX 模型文件（如 `model.int8.onnx`）。 */
    public val modelPath: File,
    /** ONNX 推理线程数；默认 1（标点模型小，多线程基本无收益）。 */
    public val numThreads: Int,
    /** 是否打开 sherpa-onnx 内部 debug 日志（仅排查时使用）。 */
    public val debug: Boolean,
) {

    /**
     * Builder：链式构造 [PunctuationConfig]。
     *
     * 必填：[modelPath]，必须是一个存在的文件。
     *
     * 典型用法（Kotlin）：
     * ```
     * val config = PunctuationConfig.Builder(File(filesDir, "asr-punct/model.int8.onnx"))
     *     .numThreads(1)
     *     .build()
     * val punct = PunctuationEngine(config)
     * val withPunct = punct.addPunctuation("我们都是木头人不会说话不会动")
     * punct.close()
     * ```
     */
    public class Builder(private val modelPath: File) {

        private var numThreads: Int = 1
        private var debug: Boolean = false

        /** 推理线程数，默认 1；建议 1~2，标点模型小，多线程提升有限。 */
        public fun numThreads(value: Int): Builder = apply {
            require(value in 1..8) { "numThreads must be in [1, 8], got $value" }
            this.numThreads = value
        }

        /** 打开 sherpa-onnx 内部 debug 日志（默认关）。 */
        public fun debug(value: Boolean): Builder = apply {
            this.debug = value
        }

        public fun build(): PunctuationConfig {
            require(modelPath.isFile) {
                "punctuation model not found: ${modelPath.absolutePath}"
            }
            return PunctuationConfig(
                modelPath = modelPath,
                numThreads = numThreads,
                debug = debug,
            )
        }
    }
}
