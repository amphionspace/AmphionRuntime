package com.lits.tts.sdk.internal

import java.io.File
import kotlin.io.path.createTempDirectory
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
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

    @Test
    fun zhEnPlateAlnumRunsReadLettersAndDigits() {
        val layout = testLayout()

        val plateIds = LitsTtsFrontend.encode(layout, "帮忙核查一下车牌号为冀R65438的情况。", "zh-en", "zh-en")
        val letterDigitIds = LitsTtsFrontend.encode(layout, "R65438", "zh-en", "zh-en")

        assertTrue(plateIds.isNotEmpty())
        assertTrue(letterDigitIds.isNotEmpty())
    }

    @Test
    fun splitForStreamingUsesStrongChinesePunctuation() {
        val layout = testLayout()

        val segments = LitsTtsFrontend.splitForStreaming(layout, "你好。欢迎使用语音合成系统！请稍等。")

        assertArrayEquals(
            arrayOf("你好.", "欢迎使用语音合成系统!", "请稍等."),
            segments.toTypedArray(),
        )
    }

    @Test
    fun splitForStreamingAvoidsEnglishFalseBreaks() {
        val layout = testLayout()

        val segments = LitsTtsFrontend.splitForStreaming(
            layout,
            "Hello world. Dr. Smith paid 3.14 dollars at 10:30 a.m. Visit example.com/test. Done.",
        )

        assertArrayEquals(
            arrayOf(
                "Hello world.",
                "Dr. Smith paid 3.14 dollars at 10:30 a.m. Visit example.com/test.",
                "Done.",
            ),
            segments.toTypedArray(),
        )
    }

    @Test
    fun splitForStreamingDoesNotCreateShortPlateFragments() {
        val layout = testLayout()

        val segments = LitsTtsFrontend.splitForStreaming(layout, "车牌冀R65438，请核查。下一条。")

        assertArrayEquals(
            arrayOf("车牌冀R65438,请核查.", "下一条."),
            segments.toTypedArray(),
        )
    }

    private fun testLayout(): LitsTtsAssetInstaller.InstalledLayout {
        val root = createTempDirectory("lits-tts-frontend-test").toFile()
        val assetRoot = File(
            "src/main/assets/lits-models/${LitsTtsAssetRegistry.assetSubPath}",
        )
        assumeTrue(
            "Frontend assets are provided separately from the code-only SDK branch",
            assetRoot.resolve("zh_en_symbols.json").isFile,
        )
        copyAsset(assetRoot, root, "chinese_lexicon.txt")
        copyAsset(assetRoot, root, "cmudict.txt")
        copyAsset(assetRoot, root, "zh_en_symbols.json")
        copyAsset(assetRoot, root, "pinyin_to_tokens.json")
        copyAsset(assetRoot, root, "arpabet_to_tokens.json")
        copyAsset(assetRoot, root, "polychar.txt")
        copyAsset(assetRoot, root, "frontend_golden.json")
        File(root, "lits_hidden_encoder.onnx").writeBytes(byteArrayOf())
        File(root, "lits_stream_decoder_chunk.ort").writeBytes(byteArrayOf())
        File(root, "lits_stream_decoder_final.ort").writeBytes(byteArrayOf())
        File(root, "vocos_vocoder.onnx").writeBytes(byteArrayOf())
        return LitsTtsAssetInstaller.InstalledLayout.of(
            rootDir = root,
            manifest = LitsTtsAssetInstaller.ManifestInfo(
                modelId = "transsion_lits_en_zh_vocos24k_streaming_proto",
                version = "0.1.0",
                sampleRate = 24_000,
                hopLength = 384,
                speakerCount = 1,
                defaultSpeakerId = 0,
                supportsStreaming = true,
                acousticModelFile = null,
                vocoderModelFile = "vocos_vocoder.onnx",
                hiddenEncoderModelFile = "lits_hidden_encoder.onnx",
                streamDecoderChunkModelFile = "lits_stream_decoder_chunk.ort",
                streamDecoderFinalModelFile = "lits_stream_decoder_final.ort",
                streamingChunkSize = 100,
                streamingPreLookaheadLen = 3,
                streamingMelCacheLen = 8,
            ),
            source = LitsTtsAssetInstaller.LayoutSource.BUNDLED_ASSET,
        )
    }

    private fun copyAsset(assetRoot: File, root: File, name: String) {
        assetRoot.resolve(name).copyTo(root.resolve(name), overwrite = true)
    }
}
