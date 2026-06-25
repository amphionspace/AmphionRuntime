package com.lits.tts.sdk.internal

import org.junit.Assert.assertEquals
import org.junit.Test

class TtsInputTextNormalizerTest {
    @Test
    fun addsLanguageSpecificTerminalPunctuationWhenMissing() {
        assertEquals(
            "\u6b22\u8fce\u4f7f\u7528\u8bed\u97f3\u5408\u6210\u3002",
            TtsInputTextNormalizer.ensureTerminalPunctuation("\u6b22\u8fce\u4f7f\u7528\u8bed\u97f3\u5408\u6210", "zh-en"),
        )
        assertEquals(
            "Welcome to TTS.",
            TtsInputTextNormalizer.ensureTerminalPunctuation("Welcome to TTS", "en-US"),
        )
    }

    @Test
    fun doesNotDuplicateExistingTerminalPunctuation() {
        listOf(
            "\u6b22\u8fce\u4f7f\u7528\u3002",
            "\u6b22\u8fce\u4f7f\u7528.",
            "\u6b22\u8fce\u4f7f\u7528!",
            "\u6b22\u8fce\u4f7f\u7528?",
            "Welcome.",
            "Welcome!",
            "Welcome?",
        ).forEach { text ->
            assertEquals(text, TtsInputTextNormalizer.ensureTerminalPunctuation(text, "zh-en"))
            assertEquals(text, TtsInputTextNormalizer.ensureTerminalPunctuation(text, "en-US"))
        }
    }

    @Test
    fun preservesTrailingWhitespaceAfterAddingPunctuation() {
        assertEquals(
            "\u6b22\u8fce\u4f7f\u7528\u3002",
            TtsInputTextNormalizer.ensureTerminalPunctuation("\u6b22\u8fce\u4f7f\u7528  ", "zh-en"),
        )
    }
}
