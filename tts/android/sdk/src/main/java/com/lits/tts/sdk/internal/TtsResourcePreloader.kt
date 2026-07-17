package com.lits.tts.sdk.internal

import android.content.Context
import com.lits.tts.sdk.TextToSpeechException
import com.lits.tts.sdk.TtsErrorCode

/** Shared first-stage resource preparation; deliberately excludes ONNX sessions. */
internal object TtsResourcePreloader {
    fun preload(context: Context?, workPath: String?) {
        val activeContext = context ?: throw TextToSpeechException(
            TtsErrorCode.CREATE_ENGINE_FAILED,
            "ApplicationContext unavailable for frontend preload",
        )
        val layout = LitsTtsAssetInstaller.ensureInstalled(activeContext, workPath)
        LitsTtsFrontend.preload(layout)
        LitsTnNormalizer.prewarmEnabled = true
        LitsTnNormalizer.prewarm(layout)
    }
}
