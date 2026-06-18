package com.amphion.police.terms

import android.content.Context
import com.k2fsa.sherpa.onnx.TextRewriteFst
import java.io.Closeable

/** 警务术语 global rewrite FST（方案 A：gazetteer 仍在 [PoliceTermsGazetteer]）。 */
internal class PoliceTermsFstRuntime private constructor(
    private val globalFst: TextRewriteFst,
) : Closeable {

    fun applyGlobal(text: String): String =
        if (text.isEmpty()) text else globalFst.normalize(text)

    override fun close() {
        globalFst.release()
    }

    companion object {
        fun create(context: Context): PoliceTermsFstRuntime {
            require(PoliceTermsFstAssets.allPresent(context)) {
                "missing police_terms FST assets; run evaluation/police_terms/sync_fsts_to_sample.sh"
            }
            val cached = PoliceTermsFstAssets.ensureCached(context)
            return PoliceTermsFstRuntime(
                globalFst = TextRewriteFst.fromFile(cached[0].absolutePath),
            )
        }
    }
}
