package com.amphion.asr

import com.amphion.asr.internal.Logger
import com.amphion.asr.internal.NativeGuard
import com.amphion.asr.internal.NativeResult
import com.k2fsa.sherpa.onnx.WetextItn
import com.k2fsa.sherpa.onnx.WetextItnConfig
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 中文 ITN 引擎：把 ASR 识别得到的「口语化中文」正规化为「书面化中文」，覆盖
 * 数字、小数、单位、日期、时间、货币、百分比、电话、身份证等场景。
 *
 * ```
 * 两点五八万 -> 2.58万
 * 幺三五七零八四 -> 1357084
 * 二零二六年五月十五日 -> 2026年5月15日
 * 三点五公里 -> 3.5公里
 * ```
 *
 * 底层封装我们 fork 的 sherpa-onnx 里 vendored 的 [WeTextProcessing](https://github.com/wenet-e2e/WeTextProcessing)
 * 三段式 runtime（tagger.fst → token reorder → verbalizer.fst）。
 *
 * # 资源占用
 *
 * - 中文 ITN tagger + verbalizer fst 总和约 2–4 MB；加载后常驻 native 堆
 * - 一段几十字的 [normalize] 大约 1–10 ms（端侧 CPU），通常可放在 ASR final 之后串行调用
 *
 * # 使用模式
 *
 * 跟 [PunctuationEngine] 一样，ITN 是「文本到文本」的纯函数式 API，独立于
 * [AsrEngine]，由业务方按需 lazy 创建：
 *
 * ```
 * val itn = WeitnEngine(
 *     WeitnConfig.Builder(taggerFile, verbalizerFile).build()
 * )
 * val out = itn.normalize(asrFinalText)
 * // app 退出 / 长时间不用时释放：
 * itn.close()
 * ```
 *
 * # 线程安全
 *
 * - [normalize] 可以从多个线程并发调用，但每次调用都是同步阻塞，建议串行排队避免抢占
 *   native FST Compose 资源
 * - [close] 是幂等的；close 后再调用 [normalize] 会返回原文本并触发
 *   [AsrErrorCode.SESSION_ALREADY_CLOSED] 错误回调
 *
 * # 错误处理
 *
 * - 构造期 native 加载失败（fst 损坏 / OpenFST 抛错）：抛 [IllegalStateException]，
 *   消息含 [AsrErrorCode.MODEL_LOAD_FAILED] 码
 * - 调用 [normalize] 时 native 抛出：返回原文本，并把错误投递到 [errorHandler]
 *   （为 null 时只打 log）
 */
public class WeitnEngine
@Throws(IllegalStateException::class)
@JvmOverloads
constructor(
    public val config: WeitnConfig,
    /**
     * 可选：[normalize] 期间 native 抛出时通过它上报。回调可能从任意调用线程触发，
     * 实现方应自行做线程切换。为 null 时错误只走 [Logger]。
     */
    private val errorHandler: ((AsrError) -> Unit)? = null,
) : AutoCloseable {

    private val nativeImpl: WetextItn = run {
        val sherpaConfig = WetextItnConfig(
            taggerFst = config.taggerPath.absolutePath,
            verbalizerFst = config.verbalizerPath.absolutePath,
            debug = config.debug,
        )
        when (val r = NativeGuard.run("WetextItn.<init>") {
            WetextItn(sherpaConfig)
        }) {
            is NativeResult.Ok -> {
                Logger.i(
                    "WeitnEngine loaded tagger=${config.taggerPath.absolutePath} " +
                        "verbalizer=${config.verbalizerPath.absolutePath}",
                )
                r.value
            }
            is NativeResult.Err -> throw IllegalStateException(
                "MODEL_LOAD_FAILED (code=${AsrErrorCode.MODEL_LOAD_FAILED}): " +
                    "failed to load WeText ITN fsts (" +
                    "tagger=${config.taggerPath.absolutePath}, " +
                    "verbalizer=${config.verbalizerPath.absolutePath}): " +
                    r.error.message,
                r.error.cause,
            )
        }
    }

    private val closed = AtomicBoolean(false)

    /** 引擎是否已经 [close]。 */
    public val isClosed: Boolean
        get() = closed.get()

    /**
     * 对 [text] 做 ITN。
     *
     * - 入参为空：原样返回（不调 native）
     * - native 抛出：原样返回 [text]，错误投递到 [errorHandler] / Logger，不向上抛
     * - 已 [close]：返回原文本，并以 [AsrErrorCode.SESSION_ALREADY_CLOSED] 投递错误
     *
     * 由于 native FST Compose 是同步阻塞，建议放到非 UI / 非 ASR callback 的工作线程调用。
     */
    public fun normalize(text: String): String {
        if (text.isEmpty()) return text
        if (closed.get()) {
            val err = AsrError(
                code = AsrErrorCode.SESSION_ALREADY_CLOSED,
                message = "WeitnEngine already closed",
            )
            reportError(err)
            return text
        }
        return when (val r = NativeGuard.run("WetextItn.normalize") {
            nativeImpl.normalize(text)
        }) {
            is NativeResult.Ok -> r.value
            is NativeResult.Err -> {
                reportError(r.error)
                text
            }
        }
    }

    /**
     * 释放底层 native 资源。幂等：多次调用安全。close 后再调用 [normalize]
     * 会返回原文本并触发 [AsrErrorCode.SESSION_ALREADY_CLOSED] 错误回调。
     */
    override fun close() {
        if (!closed.compareAndSet(false, true)) return
        NativeGuard.runQuietly("WetextItn.release") { nativeImpl.release() }
        Logger.i("WeitnEngine closed")
    }

    private fun reportError(err: AsrError) {
        Logger.w("WeitnEngine error: ${err.code} ${err.message}")
        errorHandler?.invoke(err)
    }
}
