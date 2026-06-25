package com.lits.tts.sdk.internal

internal object TtsInputTextNormalizer {
    fun ensureTerminalPunctuation(text: String, language: String): String {
        val trimmed = text.trimEnd()
        if (trimmed.isEmpty() || hasTerminalPunctuation(trimmed)) return text
        val suffix = if (language == "en-US") "." else "\u3002"
        return text.dropLast(text.length - trimmed.length) + suffix
    }

    private fun hasTerminalPunctuation(text: String): Boolean {
        return when (text.lastOrNull()) {
            '!', '?', '\u3002', '.', '\uFF01', '\uFF1F' -> true
            else -> false
        }
    }
}
