package com.k2fsa.sherpa.onnx

// Vendored from sherpa-onnx kotlin-api（与 OnlineRecognizer.kt / Vad.kt 同源）。
// 声纹 embedding extractor 的 native 配置：字段名/类型与 JNI 约定一一对应，勿改名。
data class SpeakerEmbeddingExtractorConfig(
    val model: String = "",
    var numThreads: Int = 1,
    var debug: Boolean = false,
    var provider: String = "cpu",
)
