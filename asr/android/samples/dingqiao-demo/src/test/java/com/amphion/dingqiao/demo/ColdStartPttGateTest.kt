package com.amphion.dingqiao.demo

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ColdStartPttGateTest {

    @Test
    fun releaseAndCaptureDrainBeforeEngineReadyFinishesAfterFlush() {
        val gate = ColdStartPttGate()
        val generation = gate.begin()

        assertTrue(gate.release(generation))
        assertFalse(gate.captureStopped(generation))
        val decision = gate.engineReady(generation)

        assertTrue(decision.accepted)
        assertTrue(decision.finishAfterFlush)
    }

    @Test
    fun staleEngineCannotClaimNewRequest() {
        val gate = ColdStartPttGate()
        val stale = gate.begin()
        val current = gate.begin()

        assertFalse(gate.engineReady(stale).accepted)
        assertTrue(gate.engineReady(current).accepted)
    }
}
