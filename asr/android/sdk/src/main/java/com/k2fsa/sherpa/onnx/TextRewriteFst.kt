// Kotlin JNI wrapper for kaldifst::TextNormalizer (single rule.fst cdrewrite).
package com.k2fsa.sherpa.onnx

import android.content.res.AssetManager

/**
 * 对单个 OpenFST 规则文件做文本 rewrite（与 sherpa OnlineRecognizer rule_fsts 同类引擎）。
 */
class TextRewriteFst private constructor(private var ptr: Long) {

    init {
        check(ptr != 0L) { "Failed to load TextRewriteFst" }
    }

    protected fun finalize() {
        if (ptr != 0L) {
            delete(ptr)
            ptr = 0
        }
    }

    fun release() = finalize()

    fun normalize(text: String): String =
        if (text.isEmpty() || ptr == 0L) text else normalize(ptr, text)

    companion object {
        init {
            System.loadLibrary("sherpa-onnx-jni")
        }

        fun fromFile(ruleFstPath: String): TextRewriteFst {
            val p = newFromFile(ruleFstPath)
            return TextRewriteFst(p)
        }

        fun fromAsset(assetManager: AssetManager, assetPath: String): TextRewriteFst {
            val p = newFromAsset(assetManager, assetPath)
            return TextRewriteFst(p)
        }

        @JvmStatic
        private external fun newFromFile(ruleFst: String): Long

        @JvmStatic
        private external fun newFromAsset(assetManager: AssetManager, ruleFst: String): Long
    }

    private external fun delete(ptr: Long)

    private external fun normalize(ptr: Long, text: String): String
}
