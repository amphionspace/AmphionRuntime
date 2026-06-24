package com.amphion.asr

import com.amphion.asr.internal.SessionImpl

/**
 * 单次识别会话：从 [AsrEngine.newSession] 拿到，结束时必须 [close]。
 *
 * Session 内部维护：
 * - 一个 native 流式解码状态
 * - 三条专用线程（decoder / postprocess / callback）
 *
 * 线程安全：
 * - [acceptPcmShort] / [acceptPcmFloat] 应该从 同一个录音线程 调用（典型场景就是 AudioRecord 的循环线程）
 * - [close] 可以从任意线程调用
 *
 * 数据格式：传入的 PCM 必须是 单声道、16-bit 或 float32、采样率 16000 Hz；SDK 不接受其他采样率。
 */
public class AsrSession internal constructor(private val impl: SessionImpl) : AutoCloseable {

    /**
     * 投递一段 16-bit PCM。
     *
     * @param samples 单声道、16 kHz、16-bit PCM；长度任意；建议每次 ~100ms（1600 个 sample）
     */
    public fun acceptPcmShort(samples: ShortArray) {
        impl.acceptPcmShort(samples)
    }

    /**
     * 投递一段 float32 PCM。范围必须是 [-1.0, 1.0]。
     *
     * @param samples 单声道、16 kHz、float32 PCM；长度任意；建议每次 ~100ms（1600 个 sample）
     */
    public fun acceptPcmFloat(samples: FloatArray) {
        impl.acceptPcmFloat(samples)
    }

    /**
     * 主动结束音频输入；解码器会 flush 出最后一段 final 结果，触发 [AsrCallback.onFinal]。
     *
     * 调用 [stop] 之后还可以继续 [acceptPcmShort]（会作为下一段话）；如要彻底结束请 [close]。
     */
    public fun stop() {
        impl.stop()
    }

    /**
     * 在不重启 Engine 的前提下，给当前 session 替换热词列表。
     *
     * @param words 新热词列表；空列表表示禁用本 session 的热词
     * @param score hotwords 加权分数；与 Engine 配置不同 SDK 会日志警告但仍接受
     */
    @JvmOverloads
    public fun updateHotwords(words: List<String>, score: Float = 1.5f) {
        impl.updateHotwords(words, score)
    }

    /**
     * 设置 / 替换目标说话人声纹向量（运行时可随时调用）。
     *
     * [embedding] 由 [SpeakerEnroller.enroll] 产出（多段注册的均值向量）。设置后，当目标说话人
     * 开关开启时，每段话结束会用它做声纹判定。更换目标人：重新 enroll 后再次调用本方法覆盖即可。
     *
     * 仅在 [AsrConfig] 通过 [AsrConfig.Builder.targetSpeaker] 启用了目标说话人能力时有意义。
     *
     * @param embedding 目标声纹向量；长度需与所用声纹模型维度一致
     */
    public fun setTargetSpeaker(embedding: FloatArray) {
        impl.setTargetSpeaker(embedding)
    }

    /** 清除已设置的目标说话人向量；之后即使开关开启也不会过滤（等价于放行全部）。 */
    public fun clearTargetSpeaker() {
        impl.clearTargetSpeaker()
    }

    /**
     * 目标说话人开关：运行时启用 / 关闭"只保留目标说话人"的输出门控
     * （初始状态随 [TargetSpeakerConfig.enabledByDefault]）。
     *
     * 语义为输出门控：ASR 始终流式全量识别（[AsrCallback.onPartial] 不受影响），开关只在每段话
     * 结束时决定该段 [AsrCallback.onFinal] 是否保留；被判为非目标的段改触发
     * [AsrCallback.onFinalRejected]。开关在一段话中途切换时，以该段结束时刻的状态为准。
     *
     * 注意：partial 阶段无法门控（声纹需完整语音段），开启时正在进行的那段 partial 仍按原文显示，
     * 到段末才门控。未通过 [AsrConfig.Builder.targetSpeaker] 启用能力时本调用被忽略（仅记日志）。
     *
     * @param enabled true 开启门控；false 关闭（放行全部）
     */
    public fun setTargetSpeakerEnabled(enabled: Boolean) {
        impl.setTargetSpeakerEnabled(enabled)
    }

    /**
     * 目标说话人 VAD 开关：运行时启用 / 关闭“目标人离场提前 endpoint”。
     *
     * 语义为 endpoint 增强：ASR 仍接收全量音频；当 VAD 已检测到 speech，且目标声纹已经确认后，
     * 若当前滑窗相似度连续低于 [SpeakerVadConfig.threshold]，SDK 会主动结束当前子句并触发
     * [AsrCallback.onFinal]。这用于让下游 LLM 尽早拿到目标人的完整一句话，避免被其他说话人拖住。
     *
     * 未通过 [TargetSpeakerConfig.speakerVad] 配置该能力时本调用被忽略（仅记日志）。
     */
    public fun setSpeakerVadEnabled(enabled: Boolean) {
        impl.setSpeakerVadEnabled(enabled)
    }

    /** 当前会话是否已经 [close]。 */
    public val isClosed: Boolean
        get() = impl.isClosed

    /**
     * 关闭会话并释放所有资源。多次 [close] 是幂等的。
     *
     * close 之后所有 accept* 方法会被丢弃；尚未派发的回调会被 drop。
     */
    override fun close() {
        impl.close()
    }
}
