package com.amphion.asr.internal

import com.amphion.asr.AsrLanguage
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertEquals
import org.junit.Test

class AssetRegistryTest {
    @Test
    fun `android fast-load models use ORT assets`() {
        assertEquals(
            listOf(
                "encoder.int8.ort",
                "decoder.ort",
                "joiner.int8.ort",
                "tokens.txt",
                "bbpe.vocab",
            ),
            AssetRegistry.asrBundle(AsrLanguage.ZH_EN).files,
        )
        assertEquals(
            listOf("model.int8.ort"),
            AssetRegistry.punctuationBundle().files,
        )
    }

    @Test
    fun `zh-en-only build keeps preinstall within delivered assets`() {
        val bundles = AssetRegistry.allBundles(zhEnOnly = true)

        assertTrue(AssetRegistry.isLanguageAvailable(AsrLanguage.ZH_EN, zhEnOnly = true))
        assertFalse(AssetRegistry.isLanguageAvailable(AsrLanguage.YUE_EN, zhEnOnly = true))
        assertTrue(bundles.any { it.bundleId == "zh-en/v1" })
        assertFalse(bundles.any { it.bundleId == "yue-en/v1" })
    }

    @Test
    fun `default build preserves both language bundles`() {
        val bundles = AssetRegistry.allBundles(zhEnOnly = false)

        assertTrue(AssetRegistry.isLanguageAvailable(AsrLanguage.ZH_EN, zhEnOnly = false))
        assertTrue(AssetRegistry.isLanguageAvailable(AsrLanguage.YUE_EN, zhEnOnly = false))
        assertTrue(bundles.any { it.bundleId == "zh-en/v1" })
        assertTrue(bundles.any { it.bundleId == "yue-en/v1" })
    }
}
