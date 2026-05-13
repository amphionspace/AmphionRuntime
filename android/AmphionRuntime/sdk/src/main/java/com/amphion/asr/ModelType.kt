package com.amphion.asr

/**
 * 模型族类型；与上游 sherpa-onnx 的 `OnlineModelConfig` 网络分支一一对应。
 *
 * 取值与 manifest.json 的 `model_type` 字段（小写下划线形式）映射：
 *
 * | manifest 字段 | 枚举 | 公司主推 |
 * | --- | --- | --- |
 * | zipformer / zipformer2 | TRANSDUCER | 是（streaming Zipformer） |
 * | paraformer | PARAFORMER | 否 |
 * | zipformer2_ctc | ZIPFORMER2_CTC | 否 |
 * | nemo_ctc / nemo-ctc | NEMO_CTC | 否 |
 *
 * 注意：旧版 manifest 不带 model_type 时按 [TRANSDUCER] 处理（保留向下兼容）。
 */
public enum class ModelType {
    /** Streaming Zipformer Transducer（公司默认）。文件：encoder.*.onnx + decoder.*.onnx + joiner.*.onnx */
    TRANSDUCER,

    /** Streaming Paraformer。文件：encoder.*.onnx + decoder.*.onnx（无 joiner） */
    PARAFORMER,

    /** Streaming Zipformer2 + CTC head。文件：model.*.onnx */
    ZIPFORMER2_CTC,

    /** NeMo Streaming Conformer-CTC。文件：model.*.onnx */
    NEMO_CTC,
    ;

    public companion object {
        /**
         * 把 manifest.json 的 model_type 字符串映射到 [ModelType]；
         * 未知 / 缺省 / 空串都视为 [TRANSDUCER]。
         */
        @JvmStatic
        public fun fromManifestString(s: String?): ModelType {
            if (s.isNullOrBlank()) return TRANSDUCER
            return when (s.lowercase().trim()) {
                "zipformer", "zipformer2", "transducer" -> TRANSDUCER
                "paraformer" -> PARAFORMER
                "zipformer2_ctc", "zipformer2-ctc", "ctc" -> ZIPFORMER2_CTC
                "nemo_ctc", "nemo-ctc", "nemo" -> NEMO_CTC
                else -> TRANSDUCER
            }
        }
    }
}
