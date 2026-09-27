package com.lits.tts.sdk.internal

import org.junit.Assert.assertEquals
import org.junit.Test

class TnLanguageSelectorTest {
    @Test
    fun numericUtterancesUseChineseInMixedMode() {
        for (text in listOf("0", "1", "2", "3.", "4。", "5!", "45", "123.", "三", "四", "五", "1.5", "-2", " 42 ")) {
            assertEquals(text, "zh", TnLanguageSelector.select(text, false))
        }
    }

    @Test
    fun explicitEnglishAndEnglishSentencesKeepEnglish() {
        for (text in listOf("1", "2.", "45", "1.5")) {
            assertEquals(text, "en", TnLanguageSelector.select(text, true))
        }
        for (text in listOf("Room 204.", "Hello world.", "A123", "v1.2", "")) {
            assertEquals(text, "en", TnLanguageSelector.select(text, false))
        }
        assertEquals("zh", TnLanguageSelector.select("房间204。", false))
    }
}
