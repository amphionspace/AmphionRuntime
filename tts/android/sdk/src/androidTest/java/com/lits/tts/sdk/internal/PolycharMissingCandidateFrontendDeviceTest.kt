package com.lits.tts.sdk.internal

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Test

class PolycharMissingCandidateFrontendDeviceTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val outputDir = File(
        context.getExternalFilesDir(null) ?: context.filesDir,
        "polychar-missing-device",
    ).apply { mkdirs() }

    @Test
    fun currentDeviceFrontendMatchesPolycharCandidatePinyin() {
        val inputAsset = instrumentationArg("inputAsset")
            ?: "polychar_missing_candidate_sentences_with_pinyin.txt"
        val runId = "polychar-missing-device-${System.currentTimeMillis()}"
        val resultFile = File(outputDir, "results-$runId.jsonl")
        val failFile = File(outputDir, "fail-cases-with-error-pinyin-$runId.jsonl")
        val summaryFile = File(outputDir, "summary-$runId.json")

        val layout = LitsTtsAssetInstaller.ensureInstalled(context, File(context.cacheDir, "polychar-device-work").absolutePath)
        val reversePinyin = reversePinyinMap(layout.rootDir.resolve(LitsTtsAssetRegistry.PINYIN_TO_TOKENS))
        val summary = Summary()
        val failureExamples = mutableListOf<JSONObject>()
        val startedAtMs = System.currentTimeMillis()

        InstrumentationRegistry.getInstrumentation().context.assets.open(inputAsset).bufferedReader(Charsets.UTF_8).useLines { lines ->
            lines.forEachIndexed { zeroBasedIndex, rawLine ->
                val line = rawLine.trim()
                if (line.isBlank()) return@forEachIndexed
                val row = parseLine(line, zeroBasedIndex + 1)
                val result = try {
                    val text = row.getString("text")
                    val goldenPinyin = row.getJSONArray("golden_pinyin").toStringList()
                    val normalizedText = LitsTnNormalizer.normalize(layout, text, LANGUAGE, LANGUAGE_CONTEXT)
                    val currentTokens = LitsTtsFrontend.debugTokensForNormalizedForTest(
                        layout = layout,
                        normalizedText = normalizedText,
                        language = LANGUAGE,
                        languageContext = LANGUAGE_CONTEXT,
                    )
                    val currentPinyin = tokensToPronunciationSequence(currentTokens, reversePinyin)
                    val errorPinyin = diffPinyin(currentPinyin, goldenPinyin)
                    val matched = currentPinyin == goldenPinyin
                    row
                        .put("tnText", normalizedText)
                        .put("current_pinyin", JSONArray(currentPinyin))
                        .put("pinyin_match", matched)
                        .put("current_tokens", JSONArray(currentTokens))
                        .put("error_pinyin", JSONArray(errorPinyin))
                        .put("first_error_pinyin", errorPinyin.firstOrNull() ?: JSONObject.NULL)
                } catch (error: Throwable) {
                    row
                        .put("status", "ERROR")
                        .put("error", "${error::class.java.simpleName}:${error.message}")
                }

                resultFile.appendText(result.toString() + "\n", Charsets.UTF_8)
                val isError = result.optString("status") == "ERROR"
                val matched = !isError && result.optBoolean("pinyin_match", false)
                summary.add(match = matched, error = isError)
                if (!matched || isError) {
                    failFile.appendText(result.toString() + "\n", Charsets.UTF_8)
                    if (failureExamples.size < 50) failureExamples += result
                }
            }
        }

        val summaryJson = JSONObject()
            .put("inputAsset", inputAsset)
            .put("devicePackage", context.packageName)
            .put("integrationPath", "sdk connectedDebugAndroidTest on device")
            .put("language", LANGUAGE)
            .put("languageContext", LANGUAGE_CONTEXT)
            .put("resultFile", resultFile.absolutePath)
            .put("failFile", failFile.absolutePath)
            .put("total", summary.total)
            .put("pass", summary.pass)
            .put("fail", summary.fail)
            .put("error", summary.error)
            .put("pinyinAccuracy", summary.accuracy())
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
    }

    private companion object {
        private const val LANGUAGE = "zh-en"
        private const val LANGUAGE_CONTEXT = "zh-CN"
        private val pinyinPreference = mapOf('1' to 0, '2' to 0, '3' to 0, '4' to 0, '5' to 0, '0' to 1, '6' to 2)

        private fun instrumentationArg(name: String): String? =
            InstrumentationRegistry.getArguments().getString(name)?.takeIf { it.isNotBlank() }

        private fun parseLine(line: String, oneBasedLineNumber: Int): JSONObject {
            val separator = line.lastIndexOf('-')
            require(separator > 0 && separator < line.length - 1) {
                "invalid line $oneBasedLineNumber: expected text-pinyin"
            }
            val text = line.substring(0, separator).trim()
            val pinyin = line.substring(separator + 1)
                .split(',')
                .map { it.trim() }
                .filter { it.isNotEmpty() }
            return JSONObject()
                .put("id", "polychar-missing-$oneBasedLineNumber")
                .put("line", oneBasedLineNumber)
                .put("text", text)
                .put("golden_pinyin", JSONArray(pinyin))
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
    }
}
