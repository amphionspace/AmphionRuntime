package com.amphion.dingqiao.diarization

import java.io.Closeable
import org.json.JSONObject

/** 一段连续发声，`end` 是开区间端点。不用 Kotlin 的闭区间，避免与时间端点混用时差一帧。 */
internal data class FrameSpan(val begin: Int, val end: Int)

/**
 * 引擎接口。抽出来只为一件事：`SortformerLocalClient` 的排队与收尾语义能在 JVM 单测里用假引擎
 * 验证，不必加载原生库。生产实现是 [SortformerDiarizationInference]。
 */
internal interface SortformerEngine : Closeable {
    fun feed(samples: FloatArray, flush: Boolean): SortformerFeedResult
}

/** 一次推理的结果；帧号是绝对 10 ms 帧。与鸿蒙 `SortformerDiarizationEvent` 同字段。 */
internal data class SortformerEvent(
    /** `final` 推进说话人缓存；`preview` 是不动缓存、只看当前块的一次预览。 */
    val kind: String,
    val beginFrame: Int,
    val frames: Int,
    val inferenceMs: Double,
    /** 每个槽位（4 个）内连续的发声区间，端点为 [begin, end) 的 10 ms 帧号。 */
    val runs: List<List<FrameSpan>>,
) {
    val preview: Boolean get() = kind == "preview"

    /** 该事件内每个槽位最早的发声帧，静默为 -1；身份映射按它决定出场顺序。 */
    fun firstSpeechFrames(): IntArray = IntArray(runs.size) { slot ->
        runs[slot].minOfOrNull { it.begin } ?: -1
    }
}

internal data class SortformerFeedResult(
    val events: List<SortformerEvent>,
    val melFrames: Long,
    val samples: Long,
)

/**
 * 会话自己持有的 Sortformer 引擎。音频按序喂入，整个流式状态在原生侧，这里只搬数据。
 *
 * 实现与鸿蒙共用 `sortformer_diarization.cpp`：9.92 s 块提交，块内可选预览，四个槽位是模型
 * 自己的到达顺序身份、整个会话稳定，这里不做任何聚类或重标注。
 */
internal class SortformerDiarizationInference(
    modelDir: String,
    threads: Int = 2,
    previewMs: Int = 5_000,
) : SortformerEngine {
    private var handle: Int = 0
    private var closed = false

    init {
        require(threads in 1..8) { "threads must be in [1, 8]" }
        System.loadLibrary("amphion_diarization_jni")
        handle = nativeLoad(modelDir, threads, previewFrames(previewMs))
        check(handle != 0) { "Sortformer model is not loaded" }
    }

    override fun feed(samples: FloatArray, flush: Boolean): SortformerFeedResult {
        check(!closed && handle != 0) { "Sortformer model is not loaded" }
        val rendered = nativeFeed(handle, samples, flush)
            ?: throw IllegalStateException("Sortformer returned no result")
        return parse(rendered)
    }

    override fun close() {
        if (closed) return
        closed = true
        if (handle != 0) nativeClose(handle)
        handle = 0
    }

    private external fun nativeLoad(modelDir: String, threads: Int, previewFrames: Int): Int
    private external fun nativeFeed(handle: Int, pcm: FloatArray, flush: Boolean): String?
    private external fun nativeClose(handle: Int)

    internal companion object {
        /** 预览周期（毫秒）折算成每次预览的 mel 帧数；0 关闭预览。pre-encoder 每 8 帧出一帧。 */
        fun previewFrames(previewMs: Int): Int {
            if (previewMs <= 0) return 0
            return (previewMs / 80 * 8).coerceIn(8, 984)
        }

        fun parse(rendered: String): SortformerFeedResult {
            val root = JSONObject(rendered)
            val array = root.optJSONArray("events")
            val events = ArrayList<SortformerEvent>(array?.length() ?: 0)
            for (i in 0 until (array?.length() ?: 0)) {
                val item = array!!.getJSONObject(i)
                val slots = item.optJSONArray("runs")
                val runs = ArrayList<List<FrameSpan>>(slots?.length() ?: 0)
                for (slot in 0 until (slots?.length() ?: 0)) {
                    val spans = slots!!.getJSONArray(slot)
                    val ranges = ArrayList<FrameSpan>(spans.length())
                    for (s in 0 until spans.length()) {
                        val span = spans.getJSONArray(s)
                        ranges.add(FrameSpan(span.getInt(0), span.getInt(1)))
                    }
                    runs.add(ranges)
                }
                events.add(
                    SortformerEvent(
                        kind = item.optString("kind", "final"),
                        beginFrame = item.optInt("beginFrame"),
                        frames = item.optInt("frames"),
                        inferenceMs = item.optDouble("inferenceMs", 0.0),
                        runs = runs,
                    ),
                )
            }
            return SortformerFeedResult(
                events = events,
                melFrames = root.optLong("melFrames"),
                samples = root.optLong("samples"),
            )
        }
    }
}
