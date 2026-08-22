package com.amphion.asr.internal

import com.k2fsa.sherpa.onnx.OnlineEndpointReason

internal enum class NativeEndpointTransition {
    HARD_RESTART,
    NATIVE_CHECKPOINT,
}

internal object NativeEndpointTransitionPolicy {
    fun decide(
        reason: OnlineEndpointReason,
        hasEvidence: Boolean,
        isFinalFlush: Boolean,
    ): NativeEndpointTransition =
        if (reason == OnlineEndpointReason.RULE3 && hasEvidence && !isFinalFlush) {
            NativeEndpointTransition.NATIVE_CHECKPOINT
        } else {
            NativeEndpointTransition.HARD_RESTART
        }
}
