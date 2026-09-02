package com.lits.tts.sdk.internal

import java.io.File

internal object TtsTestAssets {
    fun root(): File {
        val configured = System.getProperty("lits.tts.testAssetRoot")
        require(!configured.isNullOrBlank()) {
            "missing Gradle-provided lits.tts.testAssetRoot"
        }
        return File(configured).also { root ->
            require(root.isDirectory) { "missing prepared TTS test assets: ${root.absolutePath}" }
        }
    }
}
