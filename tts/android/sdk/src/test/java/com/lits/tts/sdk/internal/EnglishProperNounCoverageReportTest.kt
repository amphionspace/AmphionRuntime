package com.lits.tts.sdk.internal

import java.io.File
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Test

class EnglishProperNounCoverageReportTest {
    @Test
    fun generatedProperNounsReportLexiconCoverage() {
        val assetRoot = File("src/main/assets/lits-models/${LitsTtsAssetRegistry.assetSubPath}")
        val layout = LitsTtsAssetInstaller.InstalledLayout.of(
            rootDir = assetRoot,
            manifest = fakeManifest(),
            source = LitsTtsAssetInstaller.LayoutSource.BUNDLED_ASSET,
        )
        val supplement = loadSupplementKeys(assetRoot.resolve("supplement_lexicon.json"))
        val cmudict = loadCmudictKeys(assetRoot.resolve("cmudict.txt"))
        val properNouns = loadProperNouns()
        val rows = properNouns.map { word ->
            val key = word.uppercase()
            val source = when {
                key in supplement -> "supplement"
                key in cmudict -> "cmudict"
                else -> "spell_fallback_candidate"
            }
            val tokens = LitsTtsFrontend.debugTokensForTest(
                layout = layout,
                text = "$word is ready.",
                language = "en-US",
                languageContext = "en-US",
            ).joinToString(" ")
            JSONObject()
                .put("word", word)
                .put("key", key)
                .put("source", source)
                .put("tokens", tokens)
        }
        val summary = JSONObject()
            .put("total", rows.size)
            .put("supplement", rows.count { it.getString("source") == "supplement" })
            .put("cmudict", rows.count { it.getString("source") == "cmudict" })
            .put("spellFallbackCandidates", rows.count { it.getString("source") == "spell_fallback_candidate" })
            .put("rows", JSONArray(rows))
        val outDir = File("build/reports/frontend")
        outDir.mkdirs()
        File(outDir, "english_proper_noun_coverage_v254.json").writeText(summary.toString(2) + "\n", Charsets.UTF_8)
        println(summary.toString(2))
        assertTrue("expected 1000 generated proper nouns", properNouns.size == 1000)
    }

    private fun loadSupplementKeys(file: File): Set<String> {
        val entries = JSONObject(file.readText(Charsets.UTF_8)).getJSONObject("entries")
        return entries.keys().asSequence().toSet()
    }

    private fun loadCmudictKeys(file: File): Set<String> =
        file.readLines(Charsets.UTF_8)
            .asSequence()
            .map { it.trim() }
            .filter { it.isNotEmpty() && !it.startsWith("#") }
            .mapNotNull { line -> line.substringBefore('\t', "").substringBefore('(').takeIf { it.isNotBlank() } }
            .toSet()

    private fun loadProperNouns(): List<String> =
        File("src/test/resources/english_proper_nouns_1000.txt")
            .readLines(Charsets.UTF_8)
            .map { it.trim() }
            .filter { it.isNotEmpty() }

    private fun fakeManifest(): LitsTtsAssetInstaller.ManifestInfo =
        LitsTtsAssetInstaller.ManifestInfo(
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
        )

    private companion object {
        private val PROPER_NOUNS = listOf(
            "Anthropic",
            "OpenAI",
            "DeepSeek",
            "Claude",
            "Gemini",
            "ChatGPT",
            "GitHub",
            "Google",
            "Microsoft",
            "Apple",
            "Amazon",
            "Meta",
            "NVIDIA",
            "Tesla",
            "Huawei",
            "Xiaomi",
            "ByteDance",
            "Tencent",
            "Alibaba",
            "Baidu",
            "TikTok",
            "YouTube",
            "Instagram",
            "WhatsApp",
            "Zoom",
            "Slack",
            "Spotify",
            "Netflix",
            "Reddit",
            "Wikipedia",
            "Android",
            "HarmonyOS",
            "Kubernetes",
            "Docker",
            "Python",
            "JavaScript",
            "TypeScript",
            "PyTorch",
            "TensorFlow",
            "ONNX",
            "Qualcomm",
            "Samsung",
            "Lenovo",
            "Garmin",
            "Porsche",
            "Toyota",
            "Siemens",
            "Pfizer",
            "Moderna",
            "AstraZeneca",
        )
    }
}
