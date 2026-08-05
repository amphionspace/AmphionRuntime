package com.amphion.asr

import org.junit.Assert.assertTrue
import org.junit.Test

class AsrConfigColdStartTest {

    @Test
    fun defaultConfigDisablesOrtPrepacking() {
        val config = AsrConfig.Builder().build()

        assertTrue(config.disablePrepack)
    }
}
