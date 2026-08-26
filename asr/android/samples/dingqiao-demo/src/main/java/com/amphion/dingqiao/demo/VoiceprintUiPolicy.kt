package com.amphion.dingqiao.demo

/** Keeps voiceprint prerequisites visible without injecting an invalid runtime configuration. */
internal object VoiceprintUiPolicy {

    fun controlsEnabled(
        allowVoiceprint: Boolean,
        modelReady: Boolean,
        configurationLocked: Boolean,
    ): Boolean = allowVoiceprint && modelReady && !configurationLocked

    fun shouldOpenEnrollment(requestedEnabled: Boolean, hasVoiceprintId: Boolean): Boolean =
        requestedEnabled && !hasVoiceprintId
}
