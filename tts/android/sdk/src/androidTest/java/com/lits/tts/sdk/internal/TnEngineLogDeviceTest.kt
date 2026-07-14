package com.lits.tts.sdk.internal

import android.content.Context
import android.util.Log
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class TnEngineLogDeviceTest {
    @Test
    fun logsTnEngineRouteForExternalWorkPath() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val workPath = InstrumentationRegistry.getArguments().getString("workPath")?.takeIf { it.isNotBlank() }
            ?: File(context.cacheDir, "tn-engine-log-work").absolutePath
        val layout = LitsTtsAssetInstaller.ensureInstalled(context, workPath)

        Log.i(TAG, "layout=${layout.debugSummary()}")
        Log.i(TAG, "zh_tts=${layout.tnZhTts.absolutePath} exists=${layout.tnZhTts.isFile} canExecute=${layout.tnZhTts.canExecute()}")
        Log.i(TAG, "en_tts=${layout.tnEnTts.absolutePath} exists=${layout.tnEnTts.isFile} canExecute=${layout.tnEnTts.canExecute()}")

        val zh = LitsTnNormalizer.normalize(layout, "编号 1 的房间是 204，温度 -24.5 度。", "zh-en", "zh-en")
        val en = LitsTnNormalizer.normalize(layout, "status is pending.", "en-US", "en-US")
        Log.i(TAG, "zhOutput=$zh")
        Log.i(TAG, "enOutput=$en")

        assertTrue(zh.isNotBlank())
        assertTrue(en.isNotBlank())
    }

    private companion object {
        private const val TAG = "LitsTnRouteTest"
    }
}
