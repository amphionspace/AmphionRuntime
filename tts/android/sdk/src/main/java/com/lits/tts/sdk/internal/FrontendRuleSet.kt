package com.lits.tts.sdk.internal

import java.io.File
import java.util.concurrent.ConcurrentHashMap
import org.json.JSONObject

internal class FrontendRuleSet private constructor(private val replacements: List<ReplacementRule>) {
    fun apply(stage: String, text: String): String {
        var output = text
        replacements.forEach { rule ->
            if (stage in rule.stages) {
                output = rule.regex.replace(output) { match ->
                    renderReplacement(rule.replacement, match.groupValues)
                }
            }
        }
        return output
    }

    private data class ReplacementRule(
        val name: String,
        val stages: Set<String>,
        val regex: Regex,
        val replacement: String,
    )

    companion object {
        private val cache = ConcurrentHashMap<String, FrontendRuleSet>()
        val EMPTY = FrontendRuleSet(emptyList())

        fun load(file: File): FrontendRuleSet {
            if (!file.isFile) return EMPTY
            return cache.getOrPut(file.absolutePath) {
                val root = JSONObject(file.readText(Charsets.UTF_8))
                val replacements = root.optJSONArray("replacements") ?: return@getOrPut EMPTY
                val rules = buildList {
                    for (index in 0 until replacements.length()) {
                        val item = replacements.optJSONObject(index) ?: continue
                        val name = item.optString("name", "rule-$index")
                        val pattern = item.optString("pattern")
                        val replacement = item.optString("replacement")
                        val stagesJson = item.optJSONArray("stages")
                        if (pattern.isBlank() || replacement.isBlank() || stagesJson == null || stagesJson.length() == 0) {
                            continue
                        }
                        val stages = buildSet {
                            for (stageIndex in 0 until stagesJson.length()) {
                                stagesJson.optString(stageIndex).takeIf { it.isNotBlank() }?.let(::add)
                            }
                        }
                        if (stages.isNotEmpty()) {
                            add(
                                ReplacementRule(
                                    name = name,
                                    stages = stages,
                                    regex = Regex(pattern, RegexOption.IGNORE_CASE),
                                    replacement = replacement,
                                ),
                            )
                        }
                    }
                }
                FrontendRuleSet(rules)
            }
        }

        private fun renderReplacement(template: String, groups: List<String>): String {
            val output = StringBuilder(template.length)
            var index = 0
            while (index < template.length) {
                val char = template[index]
                if (char == '$' && index + 1 < template.length && template[index + 1].isDigit()) {
                    val groupIndex = template[index + 1].digitToInt()
                    output.append(groups.getOrNull(groupIndex).orEmpty())
                    index += 2
                } else {
                    output.append(char)
                    index += 1
                }
            }
            return output.toString()
        }
    }
}
