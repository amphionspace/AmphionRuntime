package com.amphion.asr.sample.eval

import android.util.Log
import com.amphion.asr.AsrCallback
import com.amphion.asr.AsrEngine
import com.amphion.asr.AsrError
import com.amphion.asr.AsrSession

/**
 * 现场识别（on-device hypothesis）包装：包装一个 [AsrSession]，吃录音管线的 PCM，
 * 给出 partial 和 final 文本，**不参与权威 WER 计算**。
 *
 * 设计要点：
 * - 评估场景每条录音的 final 通常只有 1 段（一条句子），endpoint 触发 / [stop] 触发都会 emit final
 * - 多次 endpoint 时会拼接所有 final 段；EvalRecorder 的 stop 也会触发尾段 final
 * - 任何 SDK 错误降级为 hypothesis=null，不阻塞数据采集和 WAV 写盘
 *
 * 线程：内部 callback 在 SDK 专用线程；对外通过原子赋值暴露最新 partial / final；
 * 调用方在 UI 线程 poll 即可，无需自己 synchronized。
 */
class OnDeviceTranscriber private constructor(
    private val engine: AsrEngine,
    private val sampleRate: Int,
) {

    @Volatile
    var latestPartial: String = ""
        private set

    @Volatile
    private var finalSegments: MutableList<String> = ArrayList()

    @Volatile
    private var lastError: AsrError? = null

    @Volatile
    private var session: AsrSession? = null

    @Volatile
    private var stopped: Boolean = false

    private val finalLock = Any()

    private val callback = object : AsrCallback {
        override fun onPartial(text: String) {
            if (stopped) return
            latestPartial = text
        }

        override fun onFinal(text: String, confidence: Float) {
            if (stopped) return
            synchronized(finalLock) {
                if (text.isNotEmpty()) finalSegments.add(text)
            }
            latestPartial = ""
        }

        override fun onError(error: AsrError) {
            Log.w(TAG, "AsrError ${error.code} ${error.message}")
            lastError = error
        }
    }

    fun start() {
        if (session != null || stopped) return
        try {
            session = engine.newSession(callback)
        } catch (t: Throwable) {
            Log.w(TAG, "newSession failed: ${t.message}")
        }
    }

    fun feedPcm(samples: ShortArray) {
        val s = session ?: return
        try {
            s.acceptPcmShort(samples, sampleRate)
        } catch (t: Throwable) {
            Log.w(TAG, "acceptPcmShort failed: ${t.message}")
        }
    }

    fun stop() {
        if (stopped) return
        stopped = true
        val s = session ?: return
        try {
            s.stop()
        } catch (t: Throwable) {
            Log.w(TAG, "session.stop failed: ${t.message}")
        }
    }

    /**
     * 关闭 session（不关闭 engine —— engine 由调用方共享、复用）。
     * 关闭后所有 latest* 字段仍可读，但不再更新。
     */
    fun close() {
        val s = session
        session = null
        try {
            s?.close()
        } catch (t: Throwable) {
            Log.w(TAG, "session.close failed: ${t.message}")
        }
    }

    /**
     * 把所有 endpoint final 段拼成最终 hypothesis；中间用空格分隔，避免"段间黏字"产生
     * 虚假错误（"今天 hello world"被错读成"今天helloworld"误判 WER）。
     */
    fun finalHypothesis(): String = synchronized(finalLock) {
        finalSegments.joinToString(" ").trim()
    }

    fun lastErrorOrNull(): AsrError? = lastError

    companion object {
        private const val TAG = "OnDeviceTranscriber"

        /**
         * 包装现有 engine 创建一个新的 transcriber。engine 必须由调用方负责生命周期。
         */
        fun wrap(engine: AsrEngine, sampleRate: Int = 16000): OnDeviceTranscriber =
            OnDeviceTranscriber(engine, sampleRate)
    }
}
