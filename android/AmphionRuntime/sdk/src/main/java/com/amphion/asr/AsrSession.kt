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
