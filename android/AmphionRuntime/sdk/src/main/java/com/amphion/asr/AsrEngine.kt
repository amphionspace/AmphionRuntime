package com.amphion.asr

import com.amphion.asr.internal.EngineImpl

/**
 * 引擎实例 = 一份加载到内存的模型 + 共享的 native recognizer。
 *
 * 一个 [AsrEngine] 可以创建多个 [AsrSession]（多路并发识别），每个 session 独立持有解码状态。
 *
 * 内存占用：模型文件 INT8 后约 50 MB，加载后驻留在 native 堆。
 *
 * 线程安全：所有方法可在任意线程调用；[close] 调用之后再调用其他方法会得到 [AsrErrorCode.SESSION_ALREADY_CLOSED]。
 *
 * 典型用法：
 * ```
 * val engine = AsrEngine(config)
 * val session = engine.newSession(callback)
 * session.acceptPcmFloat(samples, 16000)
 * ...
 * session.close()
 * engine.close()
 * ```
 */
public class AsrEngine
@Throws(IllegalStateException::class)
constructor(public val config: AsrConfig) : AutoCloseable {

    private val impl: EngineImpl = EngineImpl(config)

    /**
     * 创建一个新的识别会话。回调将在专用回调线程上触发。
     *
     * @param callback 识别结果回调；不能为 null
     * @return 新的 [AsrSession]，初始处于已启动状态，可以直接 [AsrSession.acceptPcmFloat]
     */
    public fun newSession(callback: AsrCallback): AsrSession =
        AsrSession(impl.newSession(callback))

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
}
