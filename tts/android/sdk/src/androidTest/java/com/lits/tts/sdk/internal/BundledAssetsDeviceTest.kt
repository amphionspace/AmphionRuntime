package com.lits.tts.sdk.internal

import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import java.io.File

class BundledAssetsDeviceTest {
    @Test fun coldInstallReuseRepairAndExternalOverride() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val work = File(context.cacheDir, "bundled-assets-regression")
        work.deleteRecursively()
        try {
            val installed = LitsTtsAssetInstaller.ensureInstalled(context, work.path)
            assertEquals(LitsTtsAssetInstaller.LayoutSource.BUNDLED_ASSET, installed.source)
            assertTrue(installed.hasRequiredFiles())
            val original = installed.symbols.readBytes()
            val timestamp = installed.vocoderModel.lastModified()
            val reused = LitsTtsAssetInstaller.ensureInstalled(context, work.path)
            assertEquals(timestamp, reused.vocoderModel.lastModified())
            assertEquals(LitsTtsAssetInstaller.LayoutSource.BUNDLED_ASSET, reused.source)
            installed.symbols.writeBytes(byteArrayOf())
            val repaired = LitsTtsAssetInstaller.ensureInstalled(context, work.path)
            assertArrayEquals(original, repaired.symbols.readBytes())
            // Existing external installations still take precedence over bundled assets.
            repaired.rootDir.resolve(".version").delete()
            repaired.rootDir.resolve(".asset_signature").delete()
            val external = LitsTtsAssetInstaller.ensureInstalled(context, work.path)
            assertEquals(LitsTtsAssetInstaller.LayoutSource.EXTERNAL_PACKAGE, external.source)
            assertEquals(repaired.rootDir, external.rootDir)
        } finally {
            work.deleteRecursively()
        }
    }
}
