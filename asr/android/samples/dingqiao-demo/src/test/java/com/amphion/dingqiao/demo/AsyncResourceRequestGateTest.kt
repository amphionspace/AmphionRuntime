package com.amphion.dingqiao.demo

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AsyncResourceRequestGateTest {
    @Test
    fun invalidatedRequest_releasesLateResource() {
        val released = mutableListOf<String>()
        val gate = AsyncResourceRequestGate<String>(released::add)
        val request = gate.begin()

        gate.invalidate()

        assertFalse(gate.accept(request, "late-engine"))
        assertEquals(listOf("late-engine"), released)
    }

    @Test
    fun currentResultQueuedForUi_isReleasedIfRequestInvalidatesBeforeUiAcceptsIt() {
        val released = mutableListOf<String>()
        val gate = AsyncResourceRequestGate<String>(released::add)
        val request = gate.begin()

        assertTrue("background callback should initially accept", gate.accept(request, "engine"))
        gate.invalidate()
        assertFalse("UI callback must recheck after queueing", gate.accept(request, "engine"))
        assertEquals(listOf("engine"), released)
    }

    @Test
    fun requestGeneration_filtersStaleAndCurrentErrors() {
        val gate = AsyncResourceRequestGate<String> {}
        val staleRequest = gate.begin()
        val currentRequest = gate.begin()

        assertFalse(gate.isCurrent(staleRequest))
        assertTrue(gate.isCurrent(currentRequest))
    }
}
