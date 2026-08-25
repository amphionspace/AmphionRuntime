package com.amphion.asr

import org.junit.Assert.assertTrue
import org.junit.Test

class AsrConfigColdStartTest {

    @Test
    fun defaultConfigDisablesOrtPrepacking() {
        val config = AsrConfig.Builder().build()

        assertTrue(config.disablePrepack)
    }

    @Test
    fun endpointRule3AcceptsOnlyDisableSentinelOrPositiveFiniteDuration() {
        val disabled = AsrConfig.Builder()
            .endpointRules(EndpointRules(rule3MinUtteranceLengthSec = -1f))
            .build()
        assertTrue(disabled.endpointRules.rule3MinUtteranceLengthSec == -1f)

        listOf(0f, -2f, Float.NaN, Float.POSITIVE_INFINITY).forEach { invalid ->
            assertTrue(
                runCatching {
                    AsrConfig.Builder().endpointRules(
                        EndpointRules(rule3MinUtteranceLengthSec = invalid),
                    )
                }.isFailure,
            )
        }
    }
}
