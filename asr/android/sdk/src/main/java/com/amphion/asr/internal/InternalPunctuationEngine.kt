package com.amphion.asr.internal

import com.amphion.asr.AsrError
import com.amphion.asr.AsrErrorCode
import com.k2fsa.sherpa.onnx.OfflinePunctuation
import com.k2fsa.sherpa.onnx.OfflinePunctuationConfig
import com.k2fsa.sherpa.onnx.OfflinePunctuationModelConfig
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 内部标点引擎：把 ASR final 文本送进 sherpa-onnx 的 OfflinePunctuation（CT-Transformer
 * 中英双语）加上「，。？」等标点。
 *
 * # 资源占用
 *
 * - INT8 模型 ~62 MB，加载后常驻 native 堆
 * - 每段几十字推理 20-100 ms（端侧 CPU）
 *
 * 仅在 [com.amphion.asr.AsrConfig.punctuation] = true 时由 [EngineImpl] 创建；
 * [PostProcessor] 串行调用，[com.amphion.asr.AsrEngine.close] 时统一 release。
 */
internal class InternalPunctuationEngine(modelFile: File, numThreads: Int) : AutoCloseable {

    private val nativeImpl: OfflinePunctuation = run {
        val cfg = OfflinePunctuationConfig(
            model = OfflinePunctuationModelConfig(
                ctTransformer = modelFile.absolutePath,
                numThreads = numThreads,
                debug = false,
                provider = "cpu",
            ),
        )
        when (val r = NativeGuard.run("OfflinePunctuation.<init>") {
            OfflinePunctuation(assetManager = null, config = cfg)
        }) {
            is NativeResult.Ok -> {
                Logger.i("InternalPunctuationEngine loaded from ${modelFile.absolutePath}")
                r.value
            }
            is NativeResult.Err -> throw IllegalStateException(
                "code=${AsrErrorCode.ASSET_INSTALL_FAILED}: " +
                    "failed to load punctuation model ${modelFile.absolutePath}: ${r.error.message}",
                r.error.cause,
            )
        }
    }

    private val closed = AtomicBoolean(false)

    /**
     * 给 [text] 加标点。
     * - 入参为空 / 已 close / native 失败：返回原文本（错误通过 [onError] 上报）
     */
    fun addPunctuation(text: String, onError: ((AsrError) -> Unit)? = null): String {
        if (text.isEmpty()) return text
        if (closed.get()) return text

        val raw = when (val r = NativeGuard.run("OfflinePunctuation.addPunctuation") {
            nativeImpl.addPunctuation(text)
        }) {
            is NativeResult.Ok -> r.value
            is NativeResult.Err -> {
                onError?.invoke(
                    AsrError(
                        AsrErrorCode.POSTPROCESS_FAILED,
                        "punctuation failed: ${r.error.message}",
                        r.error.cause,
                    ),
                )
                return text
            }
        }
        return stripLeadingPunct(raw)
    }

    /**
     * CT-Transformer 偶尔会给出形如「，今天天气真好」「。how are you」的输出——句首
     * 多了一个逗号 / 句号 / 顿号。UI 层不能容忍每行 final 都带句首标点，这里统一吃掉。
     *
     * 只剥前缀，不剥中间 / 末尾。
     */
    private fun stripLeadingPunct(s: String): String {
        if (s.isEmpty()) return s
        var i = 0
        while (i < s.length) {
            val c = s[i]
            val isPunct = c in LEADING_PUNCT_CHARS || c.isWhitespace()
            if (!isPunct) break
            i++
        }
        return if (i == 0) s else s.substring(i)
    }

    override fun close() {
        if (!closed.compareAndSet(false, true)) return
        NativeGuard.runQuietly("OfflinePunctuation.release") { nativeImpl.release() }
        Logger.i("InternalPunctuationEngine closed")
    }

    private companion object {
        private val LEADING_PUNCT_CHARS = setOf(
            ',', '.', ';', ':', '?', '!',
            '，', '。', '、', '；', '：', '？', '！',
        )
    }
}
