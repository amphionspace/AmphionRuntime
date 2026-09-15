package com.lits.tts.sdk.internal

import java.io.File
import java.security.MessageDigest
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class StudentFrontendAssetsTest {
    private val root = File(requireNotNull(System.getProperty("lits.tts.studentFrontendRoot")))
    private val symbols = JSONObject(File(root, "zh_en_symbols.json").readText())
        .getJSONArray("symbols").let { values -> List(values.length()) { values.getString(it) } }
    private val mapping = JSONObject(File(root, "pinyin_to_tokens.json").readText())
        .getJSONObject("pinyin_to_tokens")

    @Test
    fun tokenOrderMatchesTheTrainingInventory() {
        assertEquals(173, symbols.size)
        assertEquals(173, symbols.toSet().size)
        assertEquals(listOf("<blank>", "<sil>", "<unk>", "_"), symbols.take(4))
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(symbols.joinToString("\n").toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
        // Token order is the checkpoint embedding ABI, not a sortable word list.
        assertEquals("28d699a37750b24e1cb241639047df9c436e1a6917beb2706ec81bf453089e5c", digest)
    }

    @Test
    fun pinyinUsesCompleteRhymesAndKnownTokenIds() {
        assertEquals(listOf("ㄍ", "ㄨㄤ", "ˉ"), tokens("guang1"))
        assertEquals(listOf("ㄐ", "ㄧㄝ", "ˋ"), tokens("jie4"))
        assertEquals(listOf("ㄕ", "ˋ"), tokens("shi4"))
        assertEquals(listOf(38, 64), tokens("yi1").map(symbols::indexOf))
        assertEquals(3003, mapping.length())
        for (pinyin in mapping.keys()) {
            val tokens = tokens(pinyin)
            assertTrue(pinyin, tokens.isNotEmpty())
            assertTrue(pinyin, tokens.all { it in symbols })
            assertEquals(pinyin, 1, tokens.count { it in listOf("ˉ", "ˊ", "ˇ", "ˋ", "˙") })
            assertTrue(pinyin, tokens.last() in listOf("ˉ", "ˊ", "ˇ", "ˋ", "˙"))
            assertFalse(pinyin, "_" in tokens)
        }
    }

    private fun tokens(pinyin: String): List<String> {
        val values = mapping.getJSONArray(pinyin)
        return List(values.length()) { values.getString(it) }
    }
}
