package com.amphion.dingqiao.demo

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VoiceprintUiPolicyTest {

    @Test
    fun modelReadyWithoutRegistrationKeepsEnrollmentEntryReachable() {
        assertTrue(
            VoiceprintUiPolicy.controlsEnabled(
                allowVoiceprint = true,
                modelReady = true,
                configurationLocked = false,
            ),
        )
        assertTrue(VoiceprintUiPolicy.shouldOpenEnrollment(requestedEnabled = true, hasVoiceprintId = false))
    }

    @Test
    fun unsupportedOrBusyScenarioStillLocksVoiceprintControls() {
        assertFalse(
            VoiceprintUiPolicy.controlsEnabled(
                allowVoiceprint = false,
                modelReady = true,
                configurationLocked = false,
            ),
        )
        assertFalse(
            VoiceprintUiPolicy.controlsEnabled(
                allowVoiceprint = true,
                modelReady = true,
                configurationLocked = true,
            ),
        )
        assertFalse(VoiceprintUiPolicy.shouldOpenEnrollment(requestedEnabled = false, hasVoiceprintId = false))
        assertFalse(VoiceprintUiPolicy.shouldOpenEnrollment(requestedEnabled = true, hasVoiceprintId = true))
    }
}
