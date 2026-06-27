package com.amphion.asr

import com.amphion.asr.internal.EngineImpl

/**
 * 引擎实例 = 一份加载到内存的 ASR 模型 + 共享的 native recognizer + 后处理（可选 ITN / 标点 / VAD）。
 *
 * 由 [AmphionRuntime.create] 创建；业务方不能直接 `new AsrEngine`。
 *
 * 一个 [AsrEngine] 可以创建多个 [AsrSession]（多路并发识别），每个 session 独立持有解码状态。
 *
 * 内存占用：ASR 模型 INT8 ~50 MB；标点 ~62 MB；ITN ~4 MB；VAD ~2 MB；加载后驻留 native 堆。
 *
 * 线程安全：所有方法可在任意线程调用。[close] 之后再调用其他方法会得到
 * [AsrErrorCode.SESSION_ALREADY_CLOSED] 错误，不会崩溃。
 */
public class AsrEngine internal constructor(internal val impl: EngineImpl) : AutoCloseable {

    /**
     * 创建一个新的识别会话。回调将在 SDK 专用回调线程上触发。
     *
     * @param callback 识别结果回调；不能为 null
     * @param sessionConfig 会话级覆盖参数（如逐会话的 vadEnd / speaker VAD 窗口）；null 表示
     *   沿用 engine 级 [AsrConfig]。这些参数只是运行时阈值，不会触发任何 native 重建。
     * @return 新的 [AsrSession]，初始处于已启动状态，可以直接 [AsrSession.acceptPcmShort]
     */
    @JvmOverloads
    public fun newSession(callback: AsrCallback, sessionConfig: SessionConfig? = null): AsrSession =
        AsrSession(impl.newSession(callback, sessionConfig))

    /** 引擎是否已经 [close]。 */
    public val isClosed: Boolean
        get() = impl.isClosed

    /**
     * 释放引擎与所有由它创建的会话。同一引擎被多次 [close] 是幂等的。
     *
     * 一旦 close，所有未关闭的 [AsrSession] 也会被强制关闭，未投递的回调会被 drop。
     */
    override fun close() {
        impl.close()
    }

    internal companion object {
        internal fun create(impl: EngineImpl): AsrEngine = AsrEngine(impl)
    }
}
