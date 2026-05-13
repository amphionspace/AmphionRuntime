package com.yourco.asr

/**
 * 一段识别结果（partial 或 final 通用）。
 *
 * 与 `OnlineRecognizerResult` 解耦：未来即便上游字段调整，对外只增不删本数据类的字段。
 *
 * @property text 当前累计的文本（partial 是流式增量、final 是一段话最终结果）
 * @property confidence 整段平均置信度，[0.0, 1.0]；若引擎不支持恒为 1.0
 * @property tokens 与 [text] 对应的 token（subword）序列；BPE 模型下是 sentencepiece 子词
 * @property timestamps 每个 token 在音频中的起始时间（秒），与 [tokens] 等长；引擎不支持时为空
 * @property tokenConfidences 每个 token 的逐 token 置信度，与 [tokens] 等长；引擎不支持时为空
 */
public data class AsrResult(
    public val text: String,
    public val confidence: Float = 1.0f,
    public val tokens: List<String> = emptyList(),
    public val timestamps: List<Float> = emptyList(),
    public val tokenConfidences: List<Float> = emptyList(),
)
