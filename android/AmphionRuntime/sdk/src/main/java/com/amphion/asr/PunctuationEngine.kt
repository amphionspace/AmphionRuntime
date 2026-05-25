package com.amphion.asr

import com.amphion.asr.internal.Logger
import com.amphion.asr.internal.NativeGuard
import com.amphion.asr.internal.NativeResult
import com.k2fsa.sherpa.onnx.OfflinePunctuation
import com.k2fsa.sherpa.onnx.OfflinePunctuationConfig
import com.k2fsa.sherpa.onnx.OfflinePunctuationModelConfig
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 标点引擎：把 ASR 识别得到的「无标点」文本加上标点。
 *
 * 底层封装 sherpa-onnx 的 OfflinePunctuation（CT-Transformer 中英双语模型），
 * 输入纯文本，返回带标点的文本：
 *
 * ```
 * 我们都是木头人不会说话不会动 -> 我们都是木头人，不会说话，不会动。
 * how are you i am fine thank you -> How are you? I am fine. Thank you.（英文段也支持）
 * ```
 *
 * # 资源占用
 *
 * - CT-Transformer INT8 模型 ~62 MB，加载后常驻 native 堆
 * - 推理一段几十字耗时 20-100 ms（端侧 CPU），不建议放主线程或 ASR callback 线程
 *
 * # 使用模式
 *
 * 标点是「文本到文本」的纯函数式 API，独立于 [AsrEngine]：
 *
 * ```
 * val punct = PunctuationEngine(
 *     PunctuationConfig.Builder(modelFile).numThreads(1).build()
 * )
 * // 在异步线程上调用：
 * val withPunct = punct.addPunctuation(asrFinalText)
 * // app 退出 / 长时间不用时释放：
 * punct.close()
 * ```
 *
 * # 线程安全
 *
 * - [addPunctuation] 可以从多个线程并发调用，但每次调用都是同步阻塞，建议串行排队避免抢占 native
 *   推理资源
 * - [close] 是幂等的；close 后再调用 [addPunctuation] 会得到 [AsrErrorCode.SESSION_ALREADY_CLOSED]
 *   的 [AsrError]
 *
 * # 错误处理
 *
 * - 构造期 native 加载失败（模型文件损坏 / onnxruntime 抛错）：抛 [IllegalStateException]，
 *   消息含 [AsrErrorCode.MODEL_LOAD_FAILED] 码
 * - 调用 [addPunctuation] 时 native 抛出：返回原文本，并把错误投递到 [errorHandler]
 *   （为 null 时只打 log）
 */
public class PunctuationEngine
@Throws(IllegalStateException::class)
@JvmOverloads
constructor(
    public val config: PunctuationConfig,
    /**
     * 可选：[addPunctuation] 期间 native 抛出时通过它上报。回调可能从任意调用线程触发，
     * 实现方应自行做线程切换。为 null 时错误只走 [Logger]。
     */
    private val errorHandler: ((AsrError) -> Unit)? = null,
) : AutoCloseable {

    private val nativeImpl: OfflinePunctuation = run {
        val sherpaConfig = OfflinePunctuationConfig(
            model = OfflinePunctuationModelConfig(
                ctTransformer = config.modelPath.absolutePath,
                numThreads = config.numThreads,
                debug = config.debug,
                provider = "cpu",
            ),
        )
        when (val r = NativeGuard.run("OfflinePunctuation.<init>") {
            OfflinePunctuation(assetManager = null, config = sherpaConfig)
        }) {
            is NativeResult.Ok -> {
                Logger.i("PunctuationEngine loaded from ${config.modelPath.absolutePath}")
                r.value
            }
            is NativeResult.Err -> throw IllegalStateException(
                "MODEL_LOAD_FAILED (code=${AsrErrorCode.MODEL_LOAD_FAILED}): " +
                    "failed to load punctuation model ${config.modelPath.absolutePath}: ${r.error.message}",
                r.error.cause,
            )
        }
    }

    private val closed = AtomicBoolean(false)

    /** 引擎是否已经 [close]。 */
    public val isClosed: Boolean
        get() = closed.get()

    /**
     * 给 [text] 添加标点。
     *
     * - 入参为 null / 空：原样返回（不调 native）
     * - native 抛出：原样返回 [text]，错误投递到 [errorHandler] / Logger，不向上抛
     * - 已 [close]：返回原文本，并以 [AsrErrorCode.SESSION_ALREADY_CLOSED] 投递错误
     *
     * 由于 native 推理是同步阻塞 + 几十 ms 级别，建议放到非 UI / 非 ASR callback 的工作线程调用。
     */
    public fun addPunctuation(text: String): String {
        if (text.isEmpty()) return text
        if (closed.get()) {
            val err = AsrError(
                code = AsrErrorCode.SESSION_ALREADY_CLOSED,
                message = "PunctuationEngine already closed",
            )
            reportError(err)
            return text
        }
        val raw = when (val r = NativeGuard.run("OfflinePunctuation.addPunctuation") {
            nativeImpl.addPunctuation(text)
        }) {
            is NativeResult.Ok -> r.value
            is NativeResult.Err -> {
                reportError(r.error)
                text
            }
        }
        return stripLeadingPunct(raw)
    }

    /**
     * CT-Transformer 偶尔会给出形如「，今天天气真好」「。how are you」的输出——句首
     * 多了一个逗号 / 句号 / 顿号。这一般出现在 ASR 短 segment 被当成「上一句延续」推理的
     * 场景，比如粤英模型的某些断句、或者 ITN 之后字符比例突变时。
     *
     * UI 层不可能容忍「逐条 final 行都带句首逗号」，所以这里统一吃掉句首的中英文标点
     * （含空白），其余内容保持原样。
     *
     * 注意：只剥前缀，不剥中间 / 末尾。所以「.net 框架」「,123」这类要保留前缀的极端
     * 输入会被影响，但 ASR + punct 的输出几乎不会落到这种 case。
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

    /**
     * 释放底层 native 资源。幂等：多次调用安全。close 后再调用 [addPunctuation]
     * 会返回原文本并触发 [AsrErrorCode.SESSION_ALREADY_CLOSED] 错误回调。
     */
    override fun close() {
        if (!closed.compareAndSet(false, true)) return
        NativeGuard.runQuietly("OfflinePunctuation.release") { nativeImpl.release() }
        Logger.i("PunctuationEngine closed")
    }

    private fun reportError(err: AsrError) {
        Logger.w("PunctuationEngine error: ${err.code} ${err.message}")
        errorHandler?.invoke(err)
    }

    private companion object {
        private val LEADING_PUNCT_CHARS = setOf(
            ',', '.', ';', ':', '?', '!',
            '，', '。', '、', '；', '：', '？', '！',
        )
    }
}
