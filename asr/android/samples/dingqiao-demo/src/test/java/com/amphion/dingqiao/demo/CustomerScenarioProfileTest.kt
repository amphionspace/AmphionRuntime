package com.amphion.dingqiao.demo

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CustomerScenarioProfileTest {

    @Test
    fun profilesMatchHarmonyCustomerParameters() {
        assertEquals(
            CustomerScenarioProfile(
                scenario = CustomerScenario.TAP_VAD,
                audioSource = DemoAudioSource.VOICE_COMMUNICATION,
                vadBeginMs = 5_000,
                vadEndMs = 1_600,
                maxAudioDurationMs = 20_000,
                recognizerMode = "short",
                endpointMaxUtteranceMs = 20_000,
                enablePartialResult = true,
                allowVoiceprint = true,
                rotateSession = true,
                lockAudioSource = false,
            ),
            CustomerScenarioProfiles.forScenario(CustomerScenario.TAP_VAD),
        )
        assertEquals(62_000, CustomerScenarioProfiles.forScenario(CustomerScenario.PTT).maxAudioDurationMs)
        assertEquals("short", CustomerScenarioProfiles.forScenario(CustomerScenario.PTT).recognizerMode)
        assertEquals("long", CustomerScenarioProfiles.forScenario(CustomerScenario.TRANSCRIPTION).recognizerMode)
        assertEquals(60_000, CustomerScenarioProfiles.forScenario(CustomerScenario.TRANSCRIPTION).endpointMaxUtteranceMs)
        assertEquals(28_800_000, CustomerScenarioProfiles.forScenario(CustomerScenario.FORM).maxAudioDurationMs)
        assertEquals("long", CustomerScenarioProfiles.forScenario(CustomerScenario.FORM).recognizerMode)
        assertEquals(7_200_000, CustomerScenarioProfiles.forScenario(CustomerScenario.MEETING_MINUTES).maxAudioDurationMs)
        assertEquals("long", CustomerScenarioProfiles.forScenario(CustomerScenario.MEETING_MINUTES).recognizerMode)
        assertFalse(CustomerScenarioProfiles.forScenario(CustomerScenario.FORM).allowVoiceprint)
        assertTrue(CustomerScenarioProfiles.forScenario(CustomerScenario.MEETING_MINUTES).lockAudioSource)
    }

    @Test
    fun continuousRecognitionMatchesHarmonyRotationRule() {
        assertTrue(CustomerScenarioProfiles.usesContinuousRecognition(CustomerScenario.PTT))
        assertTrue(CustomerScenarioProfiles.usesContinuousRecognition(CustomerScenario.TRANSCRIPTION))
        assertFalse(CustomerScenarioProfiles.usesContinuousRecognition(CustomerScenario.TAP_VAD))
        assertFalse(CustomerScenarioProfiles.usesContinuousRecognition(CustomerScenario.FORM))
    }
}
