package com.amphion.police.person

internal data class PersonSpan(val start: Int, val end: Int)
private data class NameCandidate(val value: String, val signature: String)
private data class Replacement(val start: Int, val end: Int, val value: String)

/** Tone-aware exact-pinyin matching, gated by LAC PER spans for two-character names. */
internal class PersonNameMatcher(
    private val pinyin: Map<String, String>,
    names: List<String>,
) {
    private val candidates: List<NameCandidate>

    init {
        val bySignature = linkedMapOf<String, MutableList<String>>()
        names.map(String::trim).filter { it.length in 2..3 }.distinct().forEach { name ->
            signatureOf(name)?.let { bySignature.getOrPut(it) { mutableListOf() } += name }
        }
        candidates = bySignature.mapNotNull { (signature, values) ->
            values.singleOrNull()?.let { NameCandidate(it, signature) }
        }.sortedByDescending { it.value.length }
    }

    fun normalize(text: String, personSpans: List<PersonSpan>): String {
        if (text.isEmpty() || candidates.isEmpty()) return text
        val replacements = mutableListOf<Replacement>()
        for (target in candidates) {
            val width = target.value.length
            if (width > text.length) continue
            for (start in 0..text.length - width) {
                val end = start + width
                val overlapsPerson = personSpans.any { start < it.end && end > it.start }
                if (!overlapsPerson && width < 3) continue
                val source = text.substring(start, end)
                if (source == target.value || signatureOf(source) != target.signature) continue
                if (replacements.any { start < it.end && end > it.start }) continue
                replacements += Replacement(start, end, target.value)
            }
        }
        var output = text
        replacements.sortedByDescending { it.start }.forEach {
            output = output.substring(0, it.start) + it.value + output.substring(it.end)
        }
        return output
    }

    private fun signatureOf(text: String): String? {
        val syllables = text.map { character -> pinyin[character.toString()] ?: return null }
        return syllables.joinToString("|")
    }
}
