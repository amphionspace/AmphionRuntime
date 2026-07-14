package com.lits.tts.sdk.internal

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Test

class PronunciationRound15FrontendDeviceTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val outputDir = File(
        context.getExternalFilesDir(null) ?: context.filesDir,
        "pronunciation-round15-device",
    ).apply { mkdirs() }

    @Test
    fun currentDeviceFrontendMatchesRound15GoldenPinyin() {
        val inputAsset = instrumentationArg("inputAsset")
            ?: "pronunciation-golden-round3-results-with-pinyin-fixed-round15.jsonl"
        val useTn = instrumentationArg("useTn")?.toBooleanStrictOrNull() ?: true
        val workPath = instrumentationArg("workPath")
            ?: File(context.cacheDir, "round15-device-work").absolutePath
        val runId = "pronunciation-round15-device-${System.currentTimeMillis()}"
        val resultFile = File(outputDir, "results-$runId.jsonl")
        val failFile = File(outputDir, "fail-cases-with-error-pinyin-$runId.jsonl")
        val summaryFile = File(outputDir, "summary-$runId.json")

        val layout = LitsTtsAssetInstaller.ensureInstalled(context, workPath)
        val reversePinyin = reversePinyinMap(layout.rootDir.resolve(LitsTtsAssetRegistry.PINYIN_TO_TOKENS))
        val summary = Summary()
        val byCategory = linkedMapOf<String, Summary>()
        val failureExamples = mutableListOf<JSONObject>()
        val startedAtMs = System.currentTimeMillis()

        InstrumentationRegistry.getInstrumentation().context.assets.open(inputAsset).bufferedReader(Charsets.UTF_8).useLines { lines ->
            lines.forEach { line ->
                if (line.isBlank()) return@forEach
                val row = JSONObject(line)
                val id = row.getString("id")
                val category = row.getString("category")
                val defaultLanguage = if (category == "en-core") "en-US" else "zh-en"
                val language = row.optionalString("language") ?: defaultLanguage
                val languageContext = row.optionalString("languageContext")
                    ?: row.optionalString("language_context")
                    ?: language
                val rawText = row.optString("text", row.optString("tnText"))
                val tnText = row.optString("tnText", rawText)
                val expectedPinyin = expectedPronunciation(row)
                val result = try {
                    val currentTokens = if (useTn) {
                        LitsTtsFrontend.debugTokensForTest(layout, rawText, language, languageContext)
                    } else {
                        LitsTtsFrontend.debugTokensForNormalizedForTest(layout, tnText, language, languageContext)
                    }
                    val currentPinyin = tokensToPronunciationSequence(currentTokens, reversePinyin)
                    val errorPinyin = diffPinyin(currentPinyin, expectedPinyin)
                    val matched = currentPinyin == expectedPinyin
                    JSONObject()
                        .put("id", id)
                        .put("category", category)
                        .put("text", rawText)
                        .put("tnText", tnText)
                        .put("expected_pinyin", JSONArray(expectedPinyin))
                        .put("expected_source", expectedSource(row))
                        .put("golden_pinyin", row.optJSONArray("golden_pinyin") ?: JSONArray())
                        .put("current_pinyin", JSONArray(currentPinyin))
                        .put("round15_actual_pinyin", row.optJSONArray("actual_pinyin") ?: JSONArray())
                        .put("pinyin_match", matched)
                        .put("current_tokens", JSONArray(currentTokens))
                        .put("error_pinyin", JSONArray(errorPinyin))
                        .put("first_error_pinyin", errorPinyin.firstOrNull() ?: JSONObject.NULL)
                } catch (error: Throwable) {
                    JSONObject()
                        .put("id", id)
                        .put("category", category)
                        .put("text", rawText)
                        .put("tnText", tnText)
                        .put("status", "ERROR")
                        .put("error", "${error::class.java.simpleName}:${error.message}")
                }

                resultFile.appendText(result.toString() + "\n", Charsets.UTF_8)
                val isError = result.optString("status") == "ERROR"
                val matched = !isError && result.optBoolean("pinyin_match", false)
                summary.add(match = matched, error = isError)
                byCategory.getOrPut(category) { Summary() }.add(match = matched, error = isError)
                if (!matched || isError) {
                    failFile.appendText(result.toString() + "\n", Charsets.UTF_8)
                    if (failureExamples.size < 50) failureExamples += result
                }
            }
        }

        val summaryJson = JSONObject()
            .put("inputAsset", inputAsset)
            .put("devicePackage", context.packageName)
            .put("integrationPath", "sdk connectedDebugAndroidTest with external workPath")
            .put("useTn", useTn)
            .put("workPath", workPath)
            .put("modelLayout", layout.debugSummary())
            .put("resultFile", resultFile.absolutePath)
            .put("failFile", failFile.absolutePath)
            .put("total", summary.total)
            .put("pass", summary.pass)
            .put("fail", summary.fail)
            .put("error", summary.error)
            .put("pinyinAccuracy", summary.accuracy())
            .put("categorySummary", JSONObject().apply {
                byCategory.toSortedMap().forEach { (category, value) -> put(category, value.toJson()) }
            })
            .put("failureExamples", JSONArray(failureExamples))
            .put("startedAtMs", startedAtMs)
            .put("finishedAtMs", System.currentTimeMillis())
        summaryFile.writeText(summaryJson.toString(2) + "\n", Charsets.UTF_8)

        assertTrue("expected at least one row; see ${summaryFile.absolutePath}", summary.total > 0)
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
        private val pinyinPreference = mapOf('1' to 0, '2' to 0, '3' to 0, '4' to 0, '5' to 0, '0' to 1, '6' to 2)

        private fun instrumentationArg(name: String): String? =
            InstrumentationRegistry.getArguments().getString(name)?.takeIf { it.isNotBlank() }

        private fun expectedPronunciation(row: JSONObject): List<String> =
            row.optJSONObject("actual_sandhi_pronunciation")
                ?.optJSONArray("phonemes")
                .toStringList()
                .ifEmpty {
                    row.optJSONObject("correct_annotation")
                        ?.optJSONArray("phonemes")
                        .toStringList()
                }
                .ifEmpty { row.optJSONArray("golden_pinyin").toStringList() }

        private fun expectedSource(row: JSONObject): String =
            when {
                row.optJSONObject("actual_sandhi_pronunciation")?.optJSONArray("phonemes") != null ->
                    "actual_sandhi_pronunciation.phonemes"
                row.optJSONObject("correct_annotation")?.optJSONArray("phonemes") != null ->
                    "correct_annotation.phonemes"
                else -> "golden_pinyin"
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

        private fun diffPinyin(current: List<String>, golden: List<String>): List<JSONObject> {
            val count = maxOf(current.size, golden.size)
            return (0 until count).mapNotNull { index ->
                val currentValue = current.getOrNull(index)
                val goldenValue = golden.getOrNull(index)
                if (currentValue == goldenValue) {
                    null
                } else {
                    JSONObject()
                        .put("index", index)
                        .put("current", currentValue ?: JSONObject.NULL)
                        .put("golden", goldenValue ?: JSONObject.NULL)
                }
            }
        }

        private fun String.isArpabetLike(): Boolean =
            matches(Regex("[A-Z]+[0-2]?")) || matches(Regex("[A-Z]+[0-2]?-[A-Z]+[0-2]?"))

        private fun JSONArray?.toStringList(): List<String> {
            if (this == null) return emptyList()
            return (0 until length()).map { getString(it) }
        }

        private fun JSONObject.optionalString(name: String): String? =
            if (has(name) && !isNull(name)) optString(name).takeIf { it.isNotBlank() } else null
    }
}
