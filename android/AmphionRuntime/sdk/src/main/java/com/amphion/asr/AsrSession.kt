package com.amphion.asr

import com.amphion.asr.internal.SessionImpl

/**
 * 单次识别会话：从 [AsrEngine.newSession] 拿到，结束时必须 [close]。
 *
 * Session 内部维护：
 * - 一个 native [com.k2fsa.sherpa.onnx.OnlineStream]
 * - 一个 decode worker（专用线程，串行解码 / 派发回调）
 *
 * 线程安全：
 * - [acceptPcmFloat] / [acceptPcmShort] 应该从 同一个录音线程 调用（典型场景就是 AudioRecord 的循环线程）
 * - [close] 可以从任意线程调用
 *
 * 数据格式：传入的 PCM 必须是 单声道、16-bit 或 float32、采样率与 [AsrConfig] 一致（默认 16000Hz）。
 */
public class AsrSession internal constructor(private val impl: SessionImpl) : AutoCloseable {

    /**
     * 投递一段 float32 PCM。范围必须是 [-1.0, 1.0]。
     *
     * 不阻塞调用方；内部异步解码后通过回调 partial / final 给出结果。
     *
     * @param samples PCM 样本，长度任意；建议每次 ~ 100ms（@16kHz 即 1600 个 sample）
     * @param sampleRate 采样率，必须与 [AsrConfig] 配置的 sampleRate 一致
     */
    public fun acceptPcmFloat(samples: FloatArray, sampleRate: Int) {
        impl.acceptPcmFloat(samples, sampleRate)
    }

    /**
     * 投递一段 16-bit PCM。SDK 内部会做 short -> float 转换并归一化到 [-1.0, 1.0]。
     *
     * @param samples 16-bit PCM；长度任意；建议每次 ~100ms（@16kHz 即 1600 个 sample）
     * @param sampleRate 采样率，必须与 [AsrConfig] 配置的 sampleRate 一致
     */
    public fun acceptPcmShort(samples: ShortArray, sampleRate: Int) {
        impl.acceptPcmShort(samples, sampleRate)
    }

    /**
     * 主动结束音频输入；解码器会 flush 出最后一段 final 结果，触发 [AsrCallback.onFinal]。
     *
     * 调用 [stop] 之后还可以继续 [acceptPcmFloat]（会作为下一段话）；如要彻底结束请 [close]。
     */
    public fun stop() {
        impl.stop()
    }

    /**
     * 在不重启 Engine 的前提下，给当前 session 替换热词列表。
     *
     * 实现：在 decoder 线程上 reset 当前 stream（保留模型权重 / endpointing 状态）→
     * release 旧 stream → 用新 hotwords createStream，以最小代价让新词立刻生效。
     *
     * 注意事项：
     * - 仅词列表能在 session 级别动态调整；hotwords_score 是 Engine 级（OnlineRecognizerConfig）
     *   的属性，运行时改不了。如果传入的 [score] 与 Engine 时不同会被记录 WARN 但仍接受
     * - 切换发生在异步 decoder 线程；调用方调完立刻接下来的 [acceptPcmFloat] 会在新热词生效
     * - 切换会丢弃当前未 final 的部分识别（一段话开头出现热词调用是良好实践）
     *
     * @param words 新热词列表；空列表表示禁用本 session 的热词
     * @param score hotwords_score；如与 Engine 配置不同 SDK 会日志警告但仍接受
     */
    @JvmOverloads
    public fun updateHotwords(words: List<String>, score: Float = 1.5f) {
        impl.updateHotwords(words, score)
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
