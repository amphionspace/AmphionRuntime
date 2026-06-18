// SYNCED FROM third_party/sherpa-onnx/kotlin-api-examples/WetextItn.kt
//
// Kotlin JNI wrapper for the WeTextProcessing ITN/TN runtime vendored into
// our sherpa-onnx fork (branch `amphion-wetext`). The native side lives in
// `sherpa-onnx/csrc/wetext/` and `sherpa-onnx/jni/wetext-itn.cc`.
//
// Licensed under the Apache License, Version 2.0.

package com.k2fsa.sherpa.onnx

data class WetextItnConfig(
    var taggerFst: String = "",
    var verbalizerFst: String = "",
    var debug: Boolean = false,
)

class WetextItn(config: WetextItnConfig) {
    private var ptr: Long

    init {
        require(config.taggerFst.isNotEmpty()) { "taggerFst must not be empty" }
        require(config.verbalizerFst.isNotEmpty()) {
            "verbalizerFst must not be empty"
        }
        ptr = newFromFile(config.taggerFst, config.verbalizerFst, config.debug)
        check(ptr != 0L) {
            "Failed to create WetextItn: tagger='${config.taggerFst}' " +
                "verbalizer='${config.verbalizerFst}'"
        }
    }

    protected fun finalize() {
        if (ptr != 0L) {
            delete(ptr)
            ptr = 0
        }
    }

    fun release() = finalize()

    fun normalize(text: String): String = normalize(ptr, text)

    private external fun newFromFile(
        taggerFst: String,
        verbalizerFst: String,
        debug: Boolean,
    ): Long

    private external fun delete(ptr: Long)

    private external fun normalize(ptr: Long, text: String): String

    companion object {
        init {
            System.loadLibrary("sherpa-onnx-jni")
        }
    }
}
