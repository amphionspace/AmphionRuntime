package com.lits.tts.sdk.internal

import java.io.File
import kotlin.io.path.createTempDirectory
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class LitsTtsFrontendTest {
    @Test
    fun languageContextControlsDigitReading() {
        val layout = testLayout()

        val zhDigitIds = LitsTtsFrontend.encode(layout, "123", "zh-en", "zh-en")
        val zhTextIds = LitsTtsFrontend.encode(layout, "一二三", "zh-en", "zh-en")
        val enDigitIds = LitsTtsFrontend.encode(layout, "123", "zh-en", "en-US")

        assertArrayEquals(zhTextIds, zhDigitIds)
        assertFalse(zhDigitIds.contentEquals(enDigitIds))
    }

    @Test
    fun enUsDigitsMatchSpelledOutWords() {
        val layout = testLayout()

        val digitIds = LitsTtsFrontend.encode(layout, "Room 204 is ready.", "en-US", "en-US")
        val wordIds = LitsTtsFrontend.encode(layout, "Room two zero four is ready.", "en-US", "en-US")

        assertArrayEquals(wordIds, digitIds)
    }

    private fun testLayout(): LitsTtsAssetInstaller.InstalledLayout {
        val root = createTempDirectory("lits-tts-frontend-test").toFile()
        val assetRoot = File(
            "src/main/assets/lits-models/${LitsTtsAssetRegistry.assetSubPath}",
        )
        copyAsset(assetRoot, root, "chinese_lexicon.txt")
        copyAsset(assetRoot, root, "cmudict.txt")
        copyAsset(assetRoot, root, "zh_en_symbols.json")
        copyAsset(assetRoot, root, "pinyin_to_tokens.json")
        copyAsset(assetRoot, root, "arpabet_to_tokens.json")
        copyAsset(assetRoot, root, "polychar.txt")
        copyAsset(assetRoot, root, "frontend_golden.json")
        File(root, "lits_acoustic.onnx").writeBytes(byteArrayOf())
        File(root, "hifigan_vocoder.onnx").writeBytes(byteArrayOf())
        return LitsTtsAssetInstaller.InstalledLayout.of(
            rootDir = root,
            manifest = LitsTtsAssetInstaller.ManifestInfo(
                modelId = "lits_delivery_16k_hifigan",
                version = "1.0.0",
                sampleRate = 16_000,
                hopLength = 256,
                speakerCount = 1,
                defaultSpeakerId = 0,
                supportsStreaming = false,
                acousticModelFile = "lits_acoustic.onnx",
                vocoderModelFile = "hifigan_vocoder.onnx",
                hiddenEncoderModelFile = null,
                streamDecoderChunkModelFile = null,
                streamDecoderFinalModelFile = null,
                streamingChunkSize = -1,
                streamingPreLookaheadLen = -1,
                streamingMelCacheLen = -1,
            ),
            source = LitsTtsAssetInstaller.LayoutSource.BUNDLED_ASSET,
        )
    }

    private fun copyAsset(assetRoot: File, root: File, name: String) {
        assetRoot.resolve(name).copyTo(root.resolve(name), overwrite = true)
    }
}
