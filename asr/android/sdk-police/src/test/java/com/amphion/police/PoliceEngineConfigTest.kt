package com.amphion.police

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PoliceEngineConfigTest {
    @Test
    fun defaultWeightKeepsPresetsAndUserWords() {
        val config = PoliceEngineConfig.build(userHotwords = listOf("测试用户热词"))
        assertEquals(1.0f, config.hotwordsScore)
        assertTrue(config.hotwords.containsAll(listOf("测试用户热词 :3.0", "执法", "辽B")))
    }

    /**
     * 预置池停在 1.4.0 校准的 1.0，调用方热词必须单独带 3.0，否则「鼎桥」这类业务专名
     * 压不过同音常用词（实测被识别成「顶桥」）。
     */
    @Test
    fun callerWordsCarryTheStrongerPerWordWeight() {
        val words = PoliceEngineConfig.effectiveHotwords(userHotwords = listOf("鼎桥"))
        assertEquals("鼎桥 :3.0", words.first())
        assertTrue(words.contains("辽B"))
        assertTrue(words.none { it != words.first() && it.contains(" :") })
    }

    /** 调用方热词与预置词重名时只进池一次，不能同时出现带分和不带分两种写法。 */
    @Test
    fun callerWordMatchingAPresetIsNotDuplicated() {
        val words = PoliceEngineConfig.effectiveHotwords(userHotwords = listOf("辽B"))
        assertEquals(listOf("辽B :3.0"), words.filter { PoliceEngineConfig.displayText(it) == "辽B" })
    }

    @Test
    fun displayTextStripsThePerWordWeight() {
        assertEquals("鼎桥", PoliceEngineConfig.displayText("鼎桥 :3.0"))
        assertEquals("辽B", PoliceEngineConfig.displayText("辽B"))
    }

    @Test
    fun callerWeightOverridePreservesTheSameLexicon() {
        val defaults = PoliceEngineConfig.build()
        val custom = PoliceEngineConfig.build(hotwordsScore = 3.0f)
        assertEquals(3.0f, custom.hotwordsScore)
        assertEquals(defaults.hotwords, custom.hotwords)
    }
}
