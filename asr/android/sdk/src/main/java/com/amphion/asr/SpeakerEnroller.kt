package com.amphion.asr

import com.amphion.asr.internal.SpeakerVerifier
import com.k2fsa.sherpa.onnx.SpeakerEmbeddingExtractor
import com.k2fsa.sherpa.onnx.SpeakerEmbeddingExtractorConfig

/**
 * 目标说话人多模板注册工具（形态A）。
 *
 * 把多段注册音频转成一个目标声纹向量：每段各提 embedding -> 取均值 -> L2 归一。
 * 产出的 [FloatArray] 由业务自行持久化（如写文件 / DataStore），运行时通过
 * [AsrSession.setTargetSpeaker] 生效。
 *
 * 为什么多段（多模板）：单段注册在跨域（远场 / 方言 / 不同设备）下 EER 会显著上升；
 * 多段覆盖不同语速 / 距离 / 设备，取均值能同时抵消"短音频不稳"与"跨域漂移"两个失败域。
 * 建议 >= 3 段、每段约 5-10s、覆盖不同声学条件。
 *
 * 输入约定：每段都是单声道、16 kHz、float32 [-1.0, 1.0] 的 PCM（与 [AsrSession.acceptPcmFloat]
 * 一致）。SDK 不接管音频解码；wav/其他容器请业务侧自行解成 PCM。
 *
 * 资源：本类持有一份声纹 extractor（约 27 MB 模型），用完务必 [close]。注册是一次性离线操作，
 * 不建议与 [AsrEngine] 长期共存。
 *
 * 线程：非线程安全；请在单一后台线程使用。
 *
 * @param modelPath 声纹 embedding ONNX 模型路径（如 3D-Speaker eres2net）
 * @param numThreads 推理线程数，默认 1
 */
public class SpeakerEnroller @JvmOverloads constructor(
    modelPath: String,
    numThreads: Int = 1,
) : AutoCloseable {

    private val extractor: SpeakerEmbeddingExtractor = SpeakerEmbeddingExtractor(
        assetManager = null,
        config = SpeakerEmbeddingExtractorConfig(
            model = modelPath,
            numThreads = numThreads,
            debug = false,
            provider = "cpu",
        ),
    )

    /** 目标 embedding 维度（由模型决定，如 eres2net = 512）。 */
    public val embeddingDim: Int
        get() = extractor.dim()

    /**
     * 多段注册同一个目标说话人，产出已 L2 归一的目标向量。
     *
     * @param segments 注册音频段；每段单声道 16 kHz float32 PCM；建议 >= 3 段、每段 5-10s
     * @param sampleRate 采样率，默认 16000；当前 SDK 仅支持 16 kHz
     * @return 目标声纹向量（长度 = [embeddingDim]），供 [AsrSession.setTargetSpeaker] 使用
     * @throws IllegalArgumentException segments 为空，或所有段都太短无法提 embedding
     */
    @JvmOverloads
    public fun enroll(segments: List<FloatArray>, sampleRate: Int = 16000): FloatArray {
        require(segments.isNotEmpty()) { "enroll() needs at least 1 segment" }
        return SpeakerVerifier.enroll(extractor, segments, sampleRate)
    }

    /** 释放声纹 extractor 的 native 资源。多次调用幂等。 */
    override fun close() {
        extractor.release()
    }
}
