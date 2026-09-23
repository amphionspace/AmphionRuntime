package com.amphion.police

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PoliceEngineConfigTest {
    @Test
    fun defaultWeightKeepsPresetsAndUserWords() {
        val config = PoliceEngineConfig.build(userHotwords = listOf("测试用户热词"))
        assertEquals(1.0f, config.hotwordsScore)
        assertTrue(config.hotwords.containsAll(listOf("测试用户热词", "执法", "辽B")))
    }

    @Test
    fun callerWeightOverridePreservesTheSameLexicon() {
        val defaults = PoliceEngineConfig.build()
        val custom = PoliceEngineConfig.build(hotwordsScore = 3.0f)
        assertEquals(3.0f, custom.hotwordsScore)
        assertEquals(defaults.hotwords, custom.hotwords)
    }
}
