package com.lits.tts.sdk.internal

import java.io.File
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test

class CompactLexiconTest {
    @Test fun lookupPreservesUnicodeDuplicatesAndOverrides() {
        val file = File.createTempFile("lexicon", ".txt")
        try {
            file.writeText("光\tguang1\n重庆\tchong2 qing4\r\n光\tguang4\n坏行\n")
            val map = CompactLexicon.pinyin(file)
            assertEquals(mapOf("光" to "guang4", "重庆" to "chong2 qing4"), map)
            assertNull(map["不存在"])
            assertEquals(2, map.maxKeyLength)
            assertEquals("guang1", OverlayLexicon(mapOf("光" to "guang1"), map)["光"])
            file.writeText("A\tAH0\nA(1)\tEY1\nHELLO\tHH AH0 L OW1\n")
            val english = CompactLexicon.english(file)
            assertEquals(listOf("AH0"), english["A"])
            assertEquals(2, english.size)
            assertEquals(listOf("HH", "AH0", "L", "OW1"), english["HELLO"])
            assertEquals(listOf("AH0"), OverlayLexicon(english, mapOf("A" to listOf("EY1")))["A"])
        } finally { file.delete() }
    }

    @Test fun packagedDictionariesMatchPreviousEagerLoaderEntryForEntry() {
        val root = System.getenv("LITS_TTS_FRONTEND_REFERENCE_DIR")
        assumeTrue("explicit full dictionary parity fixture", root != null)
        val chinese = File(root!!, "chinese_lexicon.txt")
        val expectedChinese = buildMap {
            chinese.forEachLine { line ->
                val parts = line.trim().split('\t')
                if (parts.size == 2) put(parts[0], parts[1])
            }
        }
        assertEquals(expectedChinese, CompactLexicon.pinyin(chinese))
        val english = File(root, "cmudict.txt")
        val expectedEnglish = buildMap {
            english.forEachLine { line ->
                val parts = line.trim().split('\t', limit = 2)
                if (parts.size == 2) {
                    val key = parts[0].substringBefore('(').uppercase()
                    val phones = parts[1].trim().split(Regex("\\s+")).filter(String::isNotEmpty)
                    if (phones.isNotEmpty() && !containsKey(key)) put(key, phones)
                }
            }
        }
        assertEquals(expectedEnglish, CompactLexicon.english(english))
    }
}
