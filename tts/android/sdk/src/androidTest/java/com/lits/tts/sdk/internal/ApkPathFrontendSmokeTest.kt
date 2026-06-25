package com.lits.tts.sdk.internal

import androidx.test.core.app.ApplicationProvider
import java.io.File
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ApkPathFrontendSmokeTest {
    @Test
    fun installedApkAssetsUseCurrentSignatureAndFrontendBadcasesPass() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val installRoot = File(context.cacheDir, "apk-path-frontend-smoke").apply {
            deleteRecursively()
            mkdirs()
        }

        val layout = LitsTtsAssetInstaller.ensureInstalled(context, installRoot.absolutePath)
        val signatureText = layout.rootDir.resolve(".asset_signature").readText(Charsets.UTF_8)
        assertTrue(
            "asset signature should include frontend resource version",
            signatureText.contains(LitsTtsAssetRegistry.ASSET_SIGNATURE_VERSION),
        )
        assertTrue(layout.rootDir.resolve("cmudict.bin").isFile)
        assertTrue(layout.rootDir.resolve("chinese_lexicon.bin").isFile)
        assertTrue(layout.rootDir.resolve("supplement_lexicon.json").isFile)
        assertTrue(layout.rootDir.resolve("frontend_rules.json").isFile)
        assertTrue(layout.rootDir.resolve("rules_v2/zh.full.json").isFile)

        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "Type C接口已连接", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "Type-C接口已连接", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "USB C接口已连接", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "USB-C接口已连接", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "请打开chatgpt应用", "zh-en", "zh-en"),
            LitsTtsFrontend.encodeNormalized(layout, "请打开chat g p t应用", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "设备序列号TX二零二六A零九需要登记", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "设备序列号TX2026A09需要登记", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "闹钟设为十四点零五分", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "闹钟设为十四点05分", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "气温零下二十四点五度", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "气温-24.5度", "zh-en", "zh-en"),
        )
    }
}
