package com.amphion.asr.sample.police_station

import android.content.Context
import com.k2fsa.sherpa.onnx.TextRewriteFst
import java.io.Closeable

/**
 * 派出所 global / polish 两个 rewrite FST（方案 A：gazetteer 谐音仍在 [PoliceStationHomophoneDict]）。
 */
internal class PoliceStationFstRuntime private constructor(
    private val globalFst: TextRewriteFst,
    private val polishFst: TextRewriteFst,
) : Closeable {

    fun applyGlobal(text: String): String =
        if (text.isEmpty()) text else globalFst.normalize(text)

    fun applyPolish(text: String): String {
        if (text.isEmpty()) return text
        val core = polishFst.normalize(text.trim())
        return PoliceStationSentenceUtil.polishEnd(core)
    }

    override fun close() {
        globalFst.release()
        polishFst.release()
    }

    companion object {
        fun create(context: Context): PoliceStationFstRuntime {
            require(PoliceStationFstAssets.allPresent(context)) {
                "missing police_station FST assets; run sync_fsts_to_sample.sh"
            }
            val cached = PoliceStationFstAssets.ensureCached(context)
            return PoliceStationFstRuntime(
                globalFst = TextRewriteFst.fromFile(cached[0].absolutePath),
                polishFst = TextRewriteFst.fromFile(cached[1].absolutePath),
            )
        }
    }
}
