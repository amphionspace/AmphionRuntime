package com.amphion.police.plate

import android.content.Context
import com.k2fsa.sherpa.onnx.TextRewriteFst
import java.io.Closeable

/**
 * 车牌谐音 FST（方案 A：仅候选片段 char 映射，上下文规则留宿主）。
 */
internal class PlateFstRuntime private constructor(
    private val homophoneFst: TextRewriteFst,
) : Closeable {

    fun applyHomophone(segment: String): String =
        if (segment.isEmpty()) segment else homophoneFst.normalize(segment)

    override fun close() {
        homophoneFst.release()
    }

    companion object {
        fun create(context: Context): PlateFstRuntime {
            require(PlateFstAssets.allPresent(context)) {
                "missing plate FST assets; run asr/evaluation/plate_number/sync_fsts_to_sample.sh"
            }
            val cached = PlateFstAssets.ensureCached(context)
            return PlateFstRuntime(
                homophoneFst = TextRewriteFst.fromFile(cached[0].absolutePath),
            )
        }
    }
}
