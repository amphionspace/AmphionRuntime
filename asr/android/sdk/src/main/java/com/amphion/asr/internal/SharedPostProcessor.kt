package com.amphion.asr.internal

import android.content.res.AssetManager
import java.io.File

/**
 * 进程级共享的后处理资源池。
 *
 * 设计动机：标点（CT-Transformer，~70 MB native）与中文 ITN（WeText fst，~4 MB native）
 * 都是「无业务上下文、纯函数式 transform」，没必要每个 [EngineImpl] / 每条语言独立持有
 * 一份；只要多个 session 并发调用是线程安全的（sherpa-onnx 内部加锁、WeText fst 是
 * read-only），就可以单例化，常驻内存从 N×80 MB 降到 1×80 MB。
 *
 * 加载策略 = "首次调 [ensurePunctuation] / [ensureItn] 时同步 load"，[release] 时
 * 真的 free native；后续再调 ensure 会重新加载。
 *
 * 线程安全：ensure 系列用 [lock] 守护初始化；getter ([punctuation] / [itn]) 直接读
 * volatile 字段；native 调用本身（addPunctuation / normalize）由 [InternalPunctuationEngine] /
 * [InternalWeitnEngine] 各自的 closed 标记兜底。
 */
internal object SharedPostProcessor {

    @Volatile
    private var punctuation: InternalPunctuationEngine? = null

    @Volatile
    private var itn: InternalWeitnEngine? = null

    private val lock = Any()

    /**
     * 确保标点引擎已就绪。失败则保持 null，调用方按 nullable 处理。
     * 多次调用幂等：punctuation 已加载时直接返回。
     */
    fun ensurePunctuation(assetManager: AssetManager, modelPath: String) {
        if (punctuation != null) return
        synchronized(lock) {
            if (punctuation != null) return
            punctuation = try {
                InternalPunctuationEngine(assetManager, modelPath, numThreads = 1)
            } catch (t: Throwable) {
                Logger.w("SharedPostProcessor: punctuation init failed, will retry next time: ${t.message}")
                null
            }
        }
    }

    /**
     * 确保中文 ITN 引擎已就绪。失败则保持 null。
     */
    fun ensureItn(taggerFst: File, verbalizerFst: File) {
        if (itn != null) return
        synchronized(lock) {
            if (itn != null) return
            itn = try {
                InternalWeitnEngine(taggerFst, verbalizerFst)
            } catch (t: Throwable) {
                Logger.w("SharedPostProcessor: itn init failed, will retry next time: ${t.message}")
                null
            }
        }
    }

    /** 共享标点引擎；未 ensure / 加载失败时为 null。 */
    fun punctuation(): InternalPunctuationEngine? = punctuation

    /** 共享中文 ITN 引擎；未 ensure / 加载失败时为 null。 */
    fun itn(): InternalWeitnEngine? = itn

    /** 释放全部共享资源；通常仅在 [com.amphion.asr.AmphionRuntime.release] 触发。 */
    fun release() {
        synchronized(lock) {
            try { punctuation?.close() } catch (_: Throwable) {}
            try { itn?.close() } catch (_: Throwable) {}
            punctuation = null
            itn = null
        }
    }
}
