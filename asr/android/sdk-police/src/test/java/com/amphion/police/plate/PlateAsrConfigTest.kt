package com.amphion.police.plate

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PlateAsrConfigTest {

    @Test
    fun merge_plate_hotwords_with_user_dedupes() {
        val merged = PlateHotwords.mergeWithUserWords(listOf("冀R", "余铭栋"), includePreset = true)
        assertTrue(merged.contains("冀R"))
        assertTrue(merged.contains("辽B"))
        assertTrue(merged.contains("余铭栋"))
        assertEquals(1, merged.count { it == "冀R" })
    }

    @Test
    fun merge_without_preset_keeps_user_only() {
        val merged = PlateHotwords.mergeWithUserWords(listOf("测试词"), includePreset = false)
        assertEquals(listOf("测试词"), merged)
    }
}
