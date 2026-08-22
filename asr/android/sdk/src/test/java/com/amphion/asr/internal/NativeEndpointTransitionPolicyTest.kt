package com.amphion.asr.internal

import com.k2fsa.sherpa.onnx.OnlineEndpointReason
import org.junit.Assert.assertEquals
import org.junit.Test

class NativeEndpointTransitionPolicyTest {

    @Test
    fun onlyNonEmptyRule3UsesNativeCheckpoint() {
        assertEquals(
            NativeEndpointTransition.NATIVE_CHECKPOINT,
            NativeEndpointTransitionPolicy.decide(
                OnlineEndpointReason.RULE3,
                hasEvidence = true,
                isFinalFlush = false,
            ),
        )
        assertEquals(
            NativeEndpointTransition.HARD_RESTART,
            NativeEndpointTransitionPolicy.decide(
                OnlineEndpointReason.RULE3,
                hasEvidence = false,
                isFinalFlush = false,
            ),
        )
        assertEquals(
            NativeEndpointTransition.HARD_RESTART,
            NativeEndpointTransitionPolicy.decide(
                OnlineEndpointReason.RULE3,
                hasEvidence = true,
                isFinalFlush = true,
            ),
        )
        assertEquals(
            NativeEndpointTransition.HARD_RESTART,
            NativeEndpointTransitionPolicy.decide(
                OnlineEndpointReason.RULE1,
                hasEvidence = true,
                isFinalFlush = false,
            ),
        )
        assertEquals(
            NativeEndpointTransition.HARD_RESTART,
            NativeEndpointTransitionPolicy.decide(
                OnlineEndpointReason.RULE2,
                hasEvidence = true,
                isFinalFlush = false,
            ),
        )
        assertEquals(
            NativeEndpointTransition.HARD_RESTART,
            NativeEndpointTransitionPolicy.decide(
                OnlineEndpointReason.UNKNOWN,
                hasEvidence = false,
                isFinalFlush = false,
            ),
        )
    }
}
