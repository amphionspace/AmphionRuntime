package com.amphion.asr.internal

import com.amphion.asr.AsrError
import com.amphion.asr.AsrErrorCode
import com.k2fsa.sherpa.onnx.WetextItn
import com.k2fsa.sherpa.onnx.WetextItnConfig
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 内部中文 ITN 引擎：包装 sherpa-onnx 中 vendored 的 WeTextProcessing
 * tagger.fst → token reorder → verbalizer.fst 三段式 runtime。
 *
 * 输入：ASR 输出的「口语化中文」；输出：覆盖小数 / 单位 / 日期 / 时间 / 货币 /
 * 百分比 / 电话 / 身份证等场景的「书面化中文」。例：
 *
 * ```
 * 两点五八万 -> 2.58万
 * 二零二六年五月十五日 -> 2026年5月15日
 * ```
 *
 * # 资源占用
 *
 * - tagger + verbalizer fst 总和 ~2-4 MB；加载后常驻 native 堆
 * - 一段几十字 [normalize] 大约 1-10 ms
 *
 * 仅在 [com.amphion.asr.AsrConfig.itn] = true 且语言为 ZH_EN 时被 [EngineImpl] 创建。
 */
internal class InternalWeitnEngine(taggerFst: File, verbalizerFst: File) : AutoCloseable {

    private val nativeImpl: WetextItn = run {
        val cfg = WetextItnConfig(
            taggerFst = taggerFst.absolutePath,
            verbalizerFst = verbalizerFst.absolutePath,
            debug = false,
        )
        when (val r = NativeGuard.run("WetextItn.<init>") { WetextItn(cfg) }) {
            is NativeResult.Ok -> {
                Logger.i(
                    "InternalWeitnEngine loaded tagger=${taggerFst.absolutePath} " +
                        "verbalizer=${verbalizerFst.absolutePath}",
                )
                r.value
            }
            is NativeResult.Err -> throw IllegalStateException(
                "code=${AsrErrorCode.ASSET_INSTALL_FAILED}: failed to load WeText ITN fsts " +
                    "(tagger=${taggerFst.absolutePath}, verbalizer=${verbalizerFst.absolutePath}): " +
                    r.error.message,
                r.error.cause,
            )
        }
    }

    private val closed = AtomicBoolean(false)

    /**
     * 对 [text] 做 ITN。空串 / 已 close / native 失败：返回原文本（错误经 [onError] 上报）。
     */
    fun normalize(text: String, onError: ((AsrError) -> Unit)? = null): String {
        if (text.isEmpty()) return text
        if (closed.get()) return text
        return when (val r = NativeGuard.run("WetextItn.normalize") {
            nativeImpl.normalize(text)
        }) {
            is NativeResult.Ok -> r.value
            is NativeResult.Err -> {
                onError?.invoke(
                    AsrError(
                        AsrErrorCode.POSTPROCESS_FAILED,
                        "itn failed: ${r.error.message}",
                        r.error.cause,
                    ),
                )
                text
            }
        }
    }

    override fun close() {
        if (!closed.compareAndSet(false, true)) return
        NativeGuard.runQuietly("WetextItn.release") { nativeImpl.release() }
        Logger.i("InternalWeitnEngine closed")
    }
}
