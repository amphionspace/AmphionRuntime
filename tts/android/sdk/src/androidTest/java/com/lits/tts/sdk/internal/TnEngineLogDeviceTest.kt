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
        Log.i(TAG, "native_tn=liblits_tn.so")

        val zh = LitsTnNormalizer.normalize(layout, "编号 1 的房间是 204，温度 -24.5 度。", "zh-en", "zh-en")
        val zhProfile = LitsTnNormalizer.lastProfileSummary()
        val en = LitsTnNormalizer.normalize(layout, "status is pending.", "en-US", "en-US")
        val enProfile = LitsTnNormalizer.lastProfileSummary()
        Log.i(TAG, "zhOutput=$zh")
        Log.i(TAG, "zhProfile=$zhProfile")
        Log.i(TAG, "enOutput=$en")
        Log.i(TAG, "enProfile=$enProfile")

        assertTrue(zh.isNotBlank())
        assertTrue(en.isNotBlank())
        assertTrue("zh TN should use one utterance segment: $zhProfile", zhProfile?.contains(",segments=1") == true)
        assertTrue("en TN should use one utterance segment: $enProfile", enProfile?.contains(",segments=1") == true)
    }

    private companion object {
        private const val TAG = "LitsTnRouteTest"
    }
}
