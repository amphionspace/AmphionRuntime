package com.lits.tts.sdk.internal

import java.io.File
import kotlin.io.path.createTempDirectory
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test

class PronunciationRound15FrontendCorrectnessTest {
    @Test
    fun currentFrontendMatchesRound15GoldenPinyin() {
        val inputPath = System.getProperty("pronunciation.round15.input")
            ?: System.getenv("PRONUNCIATION_ROUND15_INPUT")
            ?: ""
        assumeTrue("set -Dpronunciation.round15.input=/path/to/jsonl", inputPath.isNotBlank())
        val inputFile = File(inputPath)
        assertTrue("missing round15 input JSONL: ${inputFile.absolutePath}", inputFile.isFile)

        val outputDir = File(
            System.getProperty("pronunciation.round15.outputDir")
                ?: System.getenv("PRONUNCIATION_ROUND15_OUTPUT_DIR")
                ?: "build/reports/pronunciation-round15",
        )
            .apply { mkdirs() }
        val resultFile = File(outputDir, "pronunciation-round15-frontend-results.jsonl")
        val summaryFile = File(outputDir, "pronunciation-round15-frontend-summary.json")
        resultFile.writeText("", Charsets.UTF_8)

        val layout = realAssetLayout()
        val reversePinyin = reversePinyinMap(layout.rootDir.resolve("pinyin_to_tokens.json"))
        val summary = Summary()
        val byCategory = linkedMapOf<String, Summary>()
        val failureExamples = mutableListOf<JSONObject>()

        inputFile.forEachLine(Charsets.UTF_8) { line ->
            if (line.isBlank()) return@forEachLine
            val row = JSONObject(line)
            val id = row.getString("id")
            val category = row.getString("category")
            val language = row.optString("language", "zh-en")
            val languageContext = row.optString("languageContext", row.optString("language_context", language))
            val tnText = row.getString("tnText")
            val goldenPinyin = row.optJSONArray("golden_pinyin").toStringList()
            val currentTokens = try {
                LitsTtsFrontend.debugTokensForNormalizedForTest(layout, tnText, language, languageContext)
            } catch (error: Throwable) {
                val result = JSONObject()
                    .put("id", id)
                    .put("category", category)
                    .put("text", row.optString("text"))
                    .put("tnText", tnText)
                    .put("status", "ERROR")
                    .put("error", "${error::class.java.simpleName}:${error.message}")
                resultFile.appendText(result.toString() + "\n", Charsets.UTF_8)
                summary.add(error = true)
                byCategory.getOrPut(category) { Summary() }.add(error = true)
                if (failureExamples.size < 50) failureExamples += result
                return@forEachLine
            }
            val currentPinyin = tokensToPronunciationSequence(currentTokens, reversePinyin)
            val matched = currentPinyin == goldenPinyin
            val result = JSONObject()
                .put("id", id)
                .put("category", category)
                .put("text", row.optString("text"))
                .put("tnText", tnText)
                .put("golden_pinyin", JSONArray(goldenPinyin))
                .put("current_pinyin", JSONArray(currentPinyin))
                .put("round15_actual_pinyin", row.optJSONArray("actual_pinyin") ?: JSONArray())
                .put("pinyin_match", matched)
                .put("current_tokens", JSONArray(currentTokens))
            resultFile.appendText(result.toString() + "\n", Charsets.UTF_8)
            summary.add(match = matched)
            byCategory.getOrPut(category) { Summary() }.add(match = matched)
            if (!matched && failureExamples.size < 50) failureExamples += result
        }

        val summaryJson = JSONObject()
            .put("input", inputFile.absolutePath)
            .put("resultFile", resultFile.absolutePath)
            .put("total", summary.total)
            .put("pass", summary.pass)
            .put("fail", summary.fail)
            .put("error", summary.error)
            .put("pinyinAccuracy", summary.accuracy())
            .put("categorySummary", JSONObject().apply {
                byCategory.toSortedMap().forEach { (category, value) ->
                    put(category, value.toJson())
                }
            })
            .put("failureExamples", JSONArray(failureExamples))
        summaryFile.writeText(summaryJson.toString(2) + "\n", Charsets.UTF_8)

        assertTrue("expected at least one row", summary.total > 0)
    }

    private data class Summary(
        var total: Int = 0,
        var pass: Int = 0,
        var fail: Int = 0,
        var error: Int = 0,
    ) {
        fun add(match: Boolean = false, error: Boolean = false) {
            total += 1
            if (error) {
                this.error += 1
            } else if (match) {
                pass += 1
            } else {
                fail += 1
            }
        }

        fun accuracy(): Double = if (total == 0) 0.0 else pass.toDouble() / total.toDouble()

        fun toJson(): JSONObject = JSONObject()
            .put("total", total)
            .put("pass", pass)
            .put("fail", fail)
            .put("error", error)
            .put("pinyinAccuracy", accuracy())
    }

    private companion object {
        private val assetRoot = File("src/main/assets/lits-models/${LitsTtsAssetRegistry.assetSubPath}")
        private val pinyinPreference = mapOf('1' to 0, '2' to 0, '3' to 0, '4' to 0, '5' to 0, '0' to 1, '6' to 2)

        private val sharedLayout: LitsTtsAssetInstaller.InstalledLayout by lazy {
            val root = createTempDirectory("lits-tts-pronunciation-round15").toFile()
            listOf(
                "manifest.json",
                "chinese_lexicon.txt",
                "chinese_lexicon.bin",
                "cmudict.txt",
                "cmudict.bin",
                "supplement_lexicon.json",
                "frontend_rules.json",
                "zh_en_symbols.json",
                "pinyin_to_tokens.json",
                "arpabet_to_tokens.json",
                "polychar.txt",
                "polyphone_phrases.txt",
                "chinese_surname_lexicon.txt",
                "frontend_golden.json",
                "rules_v2/zh.full.json",
                "rules_v2/en.full.json",
                "rules_v2/zh_pinyin.json",
            ).forEach { copyAsset(root, it) }
            LitsTtsAssetInstaller.InstalledLayout.of(
                rootDir = root,
                manifest = LitsTtsAssetInstaller.ManifestInfo(
                    modelId = "dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop",
                    version = "0.1.0",
                    sampleRate = 24_000,
                    hopLength = 256,
                    speakerCount = 2,
                    defaultSpeakerId = 1,
                    supportsStreaming = true,
                    acousticModelFile = null,
                    vocoderModelFile = "vocos_vocoder.onnx",
                    hiddenEncoderModelFile = "lits_hidden_encoder.onnx",
                    streamDecoderChunkModelFile = "lits_stream_decoder.onnx",
                    streamDecoderFinalModelFile = "lits_stream_decoder.onnx",
                    streamDecoderExternalLoop = true,
                    streamDecoderTimesteps = 10,
                    streamDecoderTemperature = 0.667f,
                    streamConditionChunkModelFile = "lits_stream_cond.onnx",
                    streamConditionFinalModelFile = "lits_stream_cond.onnx",
                    streamDecoderStepModelFile = "lits_stream_decoder_step.onnx",
                    streamingChunkSize = 50,
                    streamingPreLookaheadLen = 3,
                    streamingMelCacheLen = 10,
                ),
                source = LitsTtsAssetInstaller.LayoutSource.BUNDLED_ASSET,
            )
        }

        private fun realAssetLayout(): LitsTtsAssetInstaller.InstalledLayout = sharedLayout

        private fun copyAsset(root: File, name: String) {
            root.resolve(name).parentFile?.mkdirs()
            assetRoot.resolve(name).copyTo(root.resolve(name), overwrite = true)
        }

        private fun reversePinyinMap(file: File): Map<List<String>, String> {
            val obj = JSONObject(file.readText(Charsets.UTF_8)).getJSONObject("pinyin_to_tokens")
            val best = mutableMapOf<List<String>, String>()
            obj.keys().forEach { pinyin ->
                val tokens = obj.getJSONArray(pinyin).toStringList()
                putBest(best, tokens, pinyin)
                if (tokens.lastOrNull() == "_") {
                    putBest(best, tokens.dropLast(1), pinyin)
                }
            }
            return best
        }

        private fun putBest(best: MutableMap<List<String>, String>, tokens: List<String>, pinyin: String) {
            if (tokens.isEmpty()) return
            val current = best[tokens]
            if (current == null || preferPinyin(pinyin, current) < 0) {
                best[tokens] = pinyin
            }
        }

        private fun preferPinyin(left: String, right: String): Int {
            val leftTone = left.lastOrNull() ?: '9'
            val rightTone = right.lastOrNull() ?: '9'
            val rank = (pinyinPreference[leftTone] ?: 9) - (pinyinPreference[rightTone] ?: 9)
            return if (rank != 0) rank else left.compareTo(right)
        }

        private fun tokensToPronunciationSequence(tokens: List<String>, reverse: Map<List<String>, String>): List<String> {
            val output = mutableListOf<String>()
            var index = 0
            val maxLen = reverse.keys.maxOfOrNull { it.size } ?: 1
            while (index < tokens.size) {
                var matched: Pair<Int, String>? = null
                val limit = minOf(maxLen, tokens.size - index)
                for (length in limit downTo 1) {
                    val candidate = tokens.subList(index, index + length)
                    val pinyin = reverse[candidate]
                    if (pinyin != null) {
                        matched = length to pinyin
                        break
                    }
                }
                if (matched != null) {
                    output += matched.second
                    index += matched.first
                } else {
                    if (tokens[index].isArpabetLike()) {
                        output += tokens[index]
                    }
                    index += 1
                }
            }
            return output
        }

        private fun String.isArpabetLike(): Boolean =
            matches(Regex("[A-Z]+[0-2]?")) || matches(Regex("[A-Z]+[0-2]?-[A-Z]+[0-2]?"))

        private fun JSONArray?.toStringList(): List<String> {
            if (this == null) return emptyList()
            return (0 until length()).map { getString(it) }
        }
    }
}
