package com.lits.tts.sdk.internal

import java.io.File
import kotlin.io.path.createTempDirectory
import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test

class AndroidFrontendGoldenParityTest {
    @Test
    fun androidFrontendMatchesGoldenTokensAfterHostTn() {
        val goldenPath = System.getProperty("android.frontend.golden") ?: ""
        assumeTrue("set -Dandroid.frontend.golden=/path/to/golden.jsonl to run parity", goldenPath.isNotBlank())

        val goldenFile = File(goldenPath)
        assertTrue("missing Android frontend golden JSONL: ${goldenFile.path}", goldenFile.isFile)

        val layout = realAssetLayout()
        val failures = mutableListOf<String>()
        var checked = 0
        goldenFile.forEachLine(Charsets.UTF_8) { line ->
            if (line.isBlank()) return@forEachLine
            val row = JSONObject(line)
            val name = row.optString("name", "case-$checked")
            val language = row.optString("language", "zh-en")
            val languageContext = row.optString("language_context", language)
            val tnText = row.getString("tn_text")
            val expected = row.getString("cleaned_text").split(Regex("\\s+")).filter { it.isNotEmpty() }
            val actual = LitsTtsFrontend.debugTokensForNormalizedForTest(layout, tnText, language, languageContext)
            checked += 1
            if (actual != expected) {
                failures += buildString {
                    append(name).append(" token mismatch")
                    append(" raw_text=").append(row.optString("raw_text", ""))
                    append(" tn_text=").append(tnText)
                    append(" expected=").append(expected.joinToString(" "))
                    append(" actual=").append(actual.joinToString(" "))
                }
            }
        }

        assertTrue("expected to check at least one golden row", checked > 0)
        assertTrue(
            failures.take(30).joinToString(separator = "\n", prefix = "frontend parity failures:\n"),
            failures.isEmpty(),
        )
    }

    private companion object {
        private val assetRoot = File(
            "src/main/assets/lits-models/${LitsTtsAssetRegistry.assetSubPath}",
        )

        private val sharedLayout: LitsTtsAssetInstaller.InstalledLayout by lazy {
            val root = createTempDirectory("lits-tts-golden-assets-test").toFile()
            listOf(
                "chinese_lexicon.txt",
                "chinese_lexicon.bin",
                "cmudict.txt",
                "cmudict.bin",
                "supplement_lexicon.json",
                "zh_en_symbols.json",
                "pinyin_to_tokens.json",
                "arpabet_to_tokens.json",
                "polychar.txt",
                "frontend_golden.json",
            ).forEach { copyAsset(root, it) }
            File(root, "lits_acoustic.onnx").writeBytes(byteArrayOf())
            File(root, "hifigan_vocoder.onnx").writeBytes(byteArrayOf())
            LitsTtsAssetInstaller.InstalledLayout.of(
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
                    streamDecoderExternalLoop = false,
                    streamDecoderTimesteps = -1,
                    streamDecoderTemperature = Float.NaN,
                    streamConditionChunkModelFile = null,
                    streamConditionFinalModelFile = null,
                    streamDecoderStepModelFile = null,
                    streamingChunkSize = -1,
                    streamingPreLookaheadLen = -1,
                    streamingMelCacheLen = -1,
                ),
                source = LitsTtsAssetInstaller.LayoutSource.BUNDLED_ASSET,
            )
        }

        private fun realAssetLayout(): LitsTtsAssetInstaller.InstalledLayout = sharedLayout

        private fun copyAsset(root: File, name: String) {
            root.resolve(name).parentFile?.mkdirs()
            assetRoot.resolve(name).copyTo(root.resolve(name), overwrite = true)
        }
    }
}
