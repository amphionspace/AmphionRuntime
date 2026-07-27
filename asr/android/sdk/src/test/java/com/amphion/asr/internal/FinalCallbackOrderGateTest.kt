package com.amphion.asr.internal

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FinalCallbackOrderGateTest {
    @Test
    fun stoppedWaitsUntilQueuedFinalIsEnqueued() {
        val gate = FinalCallbackOrderGate()

        gate.onFinalQueued()

        assertFalse(gate.requestStopped())
        assertTrue(gate.onFinalEnqueued())
    }

    @Test
    fun stoppedIsImmediateWhenNoFinalIsPending() {
        val gate = FinalCallbackOrderGate()

        assertTrue(gate.requestStopped())
        assertFalse(gate.requestStopped())
    }

    @Test
    fun stoppedWaitsForEveryQueuedFinal() {
        val gate = FinalCallbackOrderGate()

        gate.onFinalQueued()
        gate.onFinalQueued()

        assertFalse(gate.requestStopped())
        assertFalse(gate.onFinalEnqueued())
        assertTrue(gate.onFinalEnqueued())
    }
}
