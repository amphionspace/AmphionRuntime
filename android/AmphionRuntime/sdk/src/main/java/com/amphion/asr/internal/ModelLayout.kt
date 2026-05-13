package com.amphion.asr.internal

import com.amphion.asr.ModelType
import java.io.File

/**
 * 把"模型目录 + ModelType"映射到具体的模型文件路径。
 *
 * 协议：每个 model_type 自带一组允许的文件名候选；按顺序找到第一个真实存在的就采用，
 * 找不到就让 EngineImpl 抛 [com.amphion.asr.AsrErrorCode.MODEL_FILE_MISSING]（2002）。
 *
 * 这样 SDK 无需要求所有模型文件名 100% 统一（INT8 / FP32 / fp16 同时存在时优先 INT8），
 * 也避免了硬编码单一文件名（旧实现的局限）。
 */
internal data class ResolvedFiles(
    val encoder: File? = null,
    val decoder: File? = null,
    val joiner: File? = null,
    /** zipformer2_ctc / nemo_ctc 用的单个 model 文件 */
    val model: File? = null,
    val tokens: File,
)

internal object ModelLayout {

    /**
     * 按 model_type 解析模型目录中应当存在的文件，如有缺失返回错误信息。
     *
     * @return Pair(ResolvedFiles?, errorMessage?)。要么 first 非空（成功），要么 second 非空（失败原因）。
     */
    fun resolve(modelDir: File, type: ModelType): Pair<ResolvedFiles?, String?> {
        val tokens = File(modelDir, "tokens.txt")
        if (!tokens.isFile) {
            return null to "missing tokens.txt under ${modelDir.absolutePath}"
        }

        return when (type) {
            ModelType.TRANSDUCER -> {
                val enc = pickFirst(modelDir,
                    "encoder.int8.onnx", "encoder.onnx", "encoder.fp16.onnx")
                val dec = pickFirst(modelDir,
                    "decoder.onnx", "decoder.int8.onnx", "decoder.fp16.onnx")
                val join = pickFirst(modelDir,
                    "joiner.int8.onnx", "joiner.onnx", "joiner.fp16.onnx")
                if (enc == null || dec == null || join == null) {
                    return null to "transducer requires encoder*.onnx + decoder*.onnx + joiner*.onnx under ${modelDir.absolutePath}"
                }
                ResolvedFiles(encoder = enc, decoder = dec, joiner = join, tokens = tokens) to null
            }

            ModelType.PARAFORMER -> {
                val enc = pickFirst(modelDir, "encoder.int8.onnx", "encoder.onnx")
                val dec = pickFirst(modelDir, "decoder.int8.onnx", "decoder.onnx")
                if (enc == null || dec == null) {
                    return null to "paraformer requires encoder*.onnx + decoder*.onnx under ${modelDir.absolutePath}"
                }
                ResolvedFiles(encoder = enc, decoder = dec, tokens = tokens) to null
            }

            ModelType.ZIPFORMER2_CTC, ModelType.NEMO_CTC -> {
                val m = pickFirst(modelDir, "model.int8.onnx", "model.onnx", "model.fp16.onnx")
                    ?: return null to "${type.name.lowercase()} requires model*.onnx under ${modelDir.absolutePath}"
                ResolvedFiles(model = m, tokens = tokens) to null
            }
        }
    }

    private fun pickFirst(dir: File, vararg names: String): File? {
        for (n in names) {
            val f = File(dir, n)
            if (f.isFile) return f
        }
        return null
    }
}
